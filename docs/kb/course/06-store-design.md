# 06 使用 store 设计跨帧策略

> 来源：https://booster.feishu.cn/wiki/QhaYwC8SniGAiukUQmxcQ9uZnkc（原文约 8500 字）

## 一、核心要点

- `store` 是**战术笔记本**：整场比赛存活的跨帧记忆容器，由框架在 `SoccerRuntime.__init__` 里 `self._store = SimpleNamespace()` 创建一次（`src/framework/runtime.py`），每帧 `play()` 传入的是**同一个**对象。
- 选 `SimpleNamespace` 而不是 dict：既能随手加字段，又能 `store.xxx` 简洁访问。它**没有** `get`/`set`/`inc` 方法，AttributeError 全靠 `init_store` 提前声明来避免。
- `Context` 与 `store` 的边界是全篇的核心：`Context` 是"世界告诉你的"（每帧重建、只读、`frozen=True`，改了直接抛错）；`store` 是"你告诉自己的"（随便读写、字段可随时新增）。**凡是能从本帧感知直接读到的，就别往 store 里存（存了会过期）；凡是需要跨帧才能算出来、或必须保持稳定的，就一定要放 store。**
- `init_store(store)` 在整个 Agent 生命周期只执行一次，所有字段必须在这里声明；`play()` 里访问未声明字段要靠 `getattr(store, "x", None)` 兜底。
- 项目已有三个 store 场景，分别对应三种模式：
  - `kickoff_taker`：**保持状态**。只在"刚进入开球阶段"或"原主罚不在 `active_ids`"时重选，其余帧沿用；否则 10 秒开球窗口会被三个人的反复换人耗光，定位球变自由球。
  - `normal_attacker`：**迟滞**。把上次选择作为 `preferred_id` 传进 `_select_closest_attacker`，旧人只要不超过新人 `ATTACKER_KEEP_DIST_MARGIN_M = 0.3 m` 就继续用（"卫冕优势"）。
  - `prev_phase` / `cur_phase`：**阶段边沿**。在 `play()` 最开头先 `prev_phase = cur_phase`，再 `cur_phase = phase`，后面所有 `_act_*` 都能判断"这一帧是不是刚从别的阶段切进来"。
- 球速与预测是最实用的技巧：`Context` 只给"这一帧球在哪"，两帧位置差除以 `context.dt`（约 1/30 s）就得到 `(vx, vy)`，再外推 0.5 s 得到 `ball_predict`。抢点、守门、拦截传球都应奔向"球将要到的位置"，而不是"球现在的位置"。
- 无论本帧有没有看到球，都要执行 `store.prev_ball = ball`，否则球丢失一帧后速度会算成跨越两帧的错误值。
- **四种设计模式**（原文 单元5）：
  1. **保持状态**：把当前角色/目标存进 store，下帧复用（`normal_attacker`、`kickoff_taker`）。
  2. **迟滞（hysteresis）**：允许切换，但竞争者必须超出缓冲门槛（0.3 m）才允许换，过滤感知噪声。
  3. **计数/冷却**：存时间戳，达到条件才允许再行动（`store.kick_cooldown_until = context.now + 0.6`）。时间戳方式与帧率无关，最推荐。
  4. **阶段边沿**：存上一帧 phase，检测跳变，触发且仅触发一次初始化/重置。
- 冷却的物理依据：一次完整踢球动作约 **0.5 s**，而 30 Hz 下这 0.5 s 会跑 **15 帧**；每帧都判断"离球近该踢"就会连发 15 次踢球指令，动作被反复重启打断，腿部抽搐甚至摔倒。
- 适用判断：① "结果频繁变化但代价很高"（换人要重新走位、重新绕球）→ 状态保持；② "基于连续数值比大小做离散选择"（谁离球近、球在哪个区域）→ 必须加迟滞；③ "动作需要物理时间完成或刚完成需缓冲"（射门、起身、解围）→ 冷却；④ "事件刚开始/阶段刚切换时做一次" → 边沿。
- 单帧差分有噪声（一帧的感知误差会被 `dt` 放大），进阶做法是用 store 缓存最近 N 帧做滑动平均或卡尔曼滤波——**原文只给方向，未给实现**。

## 二、代码与公式

**1）声明字段（原文 单元4，加在 `src/main.py:115 init_store`）**

```python
store.prev_ball = None             # 上一帧的球位置（BallState 或 None）
store.ball_velocity = (0.0, 0.0)   # 球的线速度 (vx, vy)
store.ball_predict = (0.0, 0.0)    # 预测的未来位置，策略直接消费
```

初值给 `(0.0, 0.0)` 而不是 `None`，能省掉下游判断。

**2）球速差分 + 0.5 s 外推（原文 单元4，插在 `play()` 里 phase 记账之后、分派 `_act_*` 之前）**

```python
ball = context.ball
if ball is not None and store.prev_ball is not None and context.dt > 0:
    vx = (ball.x - store.prev_ball.x) / context.dt
    vy = (ball.y - store.prev_ball.y) / context.dt
    store.ball_velocity = (vx, vy)
    store.ball_predict = (ball.x + vx * 0.5, ball.y + vy * 0.5)   # 0.5 s 后
store.prev_ball = ball        # 无论本帧看没看到球，都更新"上一帧"
```

公式即"平均速度 = 位移 / 时间"：

```text
v = (ball(t) - ball(t-dt)) / dt
p_pred = ball(t) + v * 0.5
```

**3）保持状态（`kickoff_taker`，原文 单元3）**

```python
active_ids = {p.id for p in players}
if store.prev_phase != Phase.OUR_KICKOFF or store.kickoff_taker not in active_ids:
    store.kickoff_taker = _select_closest_attacker(context, players).id
```

**4）迟滞（`normal_attacker`，原文 单元3）**

```python
attacker = _select_closest_attacker(context, players, getattr(store, "normal_attacker", None))
store.normal_attacker = attacker.id
```

`_select_closest_attacker` 内部（`src/main.py:220-224`）：`preferred[1] <= best_dist + ATTACKER_KEEP_DIST_MARGIN_M` 就返回旧人。

**5）阶段边沿（`prev_phase`/`cur_phase`，原文 单元3）**

```python
phase = get_phase(context)
store.prev_phase = store.cur_phase
store.cur_phase = phase
```

**6）练习：追球者 3 秒锁定（原文 章节练习）**

```python
# init_store
store.attacker_id = None
store.attacker_since = None          # 用 context.now 记时间戳

# _act_normal
now = context.now
if (store.attacker_id is not None
        and now - (store.attacker_since or 0) < 3.0):
    attacker = next(p for p in players if p.id == store.attacker_id)
else:
    attacker = _select_closest_attacker(context, players)
    store.attacker_id = attacker.id
    store.attacker_since = now
```

`(store.attacker_since or 0)` 防止时间戳为 `None` 时相减报错。这是"状态保持 + 冷却"的组合：`attacker_id` 存结果，`attacker_since` 存时刻。

## 三、易错点

- **【原文】** 每帧重选开球主罚者：第 1 帧派 A、第 2 帧派 B、第 3 帧又派 A，三个人原地不动，10 秒开球窗口白白耗尽。
- **【原文】** 基于距离选角色不加迟滞：1 号 2.51 m、2 号 2.49 m 来回震荡，`attacker` 每帧横跳，"两个人在场上像跳舞一样原地扭动"。
- **【原文】** 射门后不加冷却：0.5 s 的踢球动作被 15 帧指令反复重启，机器人腿部抽搐甚至摔倒。
- **【原文】** 字段没在 `init_store` 声明就访问，可能 `AttributeError`；即使 `getattr(..., None)` 兜底，后续若假设它是 list/float 仍会出错。
- **【原文】** 用"两帧差"算速度有噪声，一帧的感知误差会被放大；需要平滑（原文未给实现）。
- **【经验建议】** 本仓库 `play()` 是 `@staticmethod`（`src/main.py:122-123`），没有 `self`；`context.dt` 在球丢帧时可能对应跨了多帧，建议给 `dt` 加上限（如 `dt = min(context.dt, 0.1)`）再除，否则一次丢帧会算出巨大的假速度。
- **【经验建议】** `next(p for p in players if p.id == store.attacker_id)` 在锁定期内该球员摔倒/被罚下时会 `StopIteration` 崩溃；应写 `next((p for p in players if p.id == store.attacker_id), None)`，为 `None` 时立即重选并刷新 `attacker_since`。
- **【经验建议】** 不要用本地计时判断"球权已开放/可以返场"，只认 `context.game` 的 `secondary_time`、`set_play`、`kicking_team`；`store` 的计时只能用于战术冷却，不能用于规则判定。

## 四、对本项目的具体改进建议

1. **`src/main.py:115 init_store`：补齐跨帧字段。** 追加 `prev_ball`、`ball_velocity`、`ball_predict`、`kick_cooldown_until = 0.0`、`attacker_since = None`、`last_phase_change_at = None`。全部带注释与初值，避免 `AttributeError`。
2. **`src/main.py:123 play`：插入球速差分块。** 位置在 `store.cur_phase = phase`（第 126 行）之后、`_analyze_and_draw`（第 129 行）之前；按上面第 2 段代码原样落地，`dt` 做 `min(..., 0.1)` 保护；末尾无条件 `store.prev_ball = ball`。注意 `play` 是静态方法，直接用参数 `store`。
3. **`src/main.py:228 _act_normal`：让 attacker 奔向预测点。** 新增 `Player.attack_point(point)`（`src/player.py`，与 `attack()` 同构，但 `_behind_ball` 的 `aim` 与 `walk_to` 目标改为预测点，进入 `KICK_ENTER_M` 后仍 `plan_kick()` 朝门踢）；`_act_normal` 里改为 `attacker.attack_point(store.ball_predict)`。**不要**直接把 `ball_predict` 塞进 `attack(kick_target)`——那个参数只影响绕后方向，不改变实际踢球方向，会造成"绕到预测点、却朝门中心踢"的错位。
4. **`src/player.py:595 guard()`：用预测点提前横移。** 增加可选参数 `guard(ball_point=None)`；`_act_normal` 里把 `store.ball_predict` 传进去，`face` 仍朝球，站位 y 用 `clamp(pred_y, -1.5, 1.5)`，x 仍取 `own_goal_area_center` 的 x（或威胁前压，见 05 改进 1）。
5. **射门冷却（防连踢）。** 在 `_act_our_kickoff`（`src/main.py:273` 的 `kick(...)` 之后）与 `_act_normal` 的踢球分支里，踢完立刻 `store.kick_cooldown_until = context.now + 0.6`；后续帧在 `context.now < store.kick_cooldown_until` 时只做 `walk_to` 调整、不再发 `kick`。注意 `Player.attack()` 内部每帧都会调 `kick()`，所以冷却判断要放在 `attack()` 之前（策略层），或给 `attack()` 加 `power=0` 之外的跳过分支。
6. **3 秒锁定 + 距离迟滞的组合（练习落地）。** 在 `_act_normal` 里先用"3 秒冷却"锁 `attacker_id`，锁定期满后再用 `_select_closest_attacker(..., preferred_id)` 的 0.3 m 迟滞决定是否换人；两者串联可同时避免"高频抖动"和"锁死不动"——原文练习的参考答案也指出：时间锁定实现简单但不够灵活，距离迟滞更贴合局势但参数不当仍会抖。
7. **`src/main.py:191 _clear_normal_sticky`：扩展清理范围。** 现在只清 `normal_attacker`；建议同时清 `attacker_since`、`ball_predict` 之外的本阶段残留（如 `support_target`），保证阶段切换后的一次性重置语义。

## 五、原文关键摘录

| 维度 | `Context` | `store` |
|---|---|---|
| **生命周期** | 每帧重建，用完即弃 | 整场比赛存活，只在开赛前 `init_store` 一次 |
| **可变性** | 只读（`frozen=True`，改了直接抛错） | 随便读写，字段可以随时新增 |
| **数据来源** | 框架从感知/裁判机构造，"客观事实" | 你自己写进去的，"主观记忆与推算" |
| **用途** | 回答"现在世界什么样" | 回答"刚才发生了什么、我之前决定了什么" |
| **典型字段** | `ball`、`teammates`、`opponents`、`game`、`now`、`dt` | `prev_phase`、`normal_attacker`、`kickoff_taker`、`prev_ball` |
| **示例（读）** | `context.ball.x` → 球现在在哪 | `store.prev_ball.x` → 球上一帧在哪 |
| **示例（写）** | ❌ 不允许（`ctx.ball.x = 1` 抛错） | ✅ `store.ball_velocity = (vx, vy)` |
| **丢失风险** | 不会（每帧新鲜构造） | 字段没在 `init_store` 声明就可能 `AttributeError` |

| 模式 | 行为 | 典型字段 |
|---|---|---|
| **保持状态** | 把"当前角色/目标"存进 store，下帧复用 | `normal_attacker`、`kickoff_taker` |
| **迟滞（hysteresis）** | 存"当前选中者"，下次只在差距超过阈值时才换 | `normal_attacker` + `ATTACKER_KEEP_DIST_MARGIN_M` |
| **计数 / 冷却** | 存计数器或时间戳，达到条件才允许再行动 | `store.kick_cooldown_until` |
| **阶段边沿** | 存上一帧 phase，检测跳变触发一次性逻辑 | `prev_phase` / `cur_phase` |

> 原文："`Context` 是'世界告诉你的'，`store` 是'你告诉自己的'。凡是能从本帧感知直接读到的，就别往 `store` 里存（存了反而会过期）；凡是需要跨帧才能算出来或必须保持稳定的，就一定要放 `store`。"
>
> 原文："球员抬脚射门完成一次完整踢球动作大约需要 0.5 秒，但代码在这 0.5 秒内会跑 15 帧。如果每帧都判断'离球近，该踢'，就会连发 15 次踢球指令……加上冷却后，踢完立刻记录 `store.kick_cooldown_until` = context.now + 0.6。"
>
> 原文（练习答案）："时间锁定：实现极简单，能彻底杜绝高频震荡。劣势：不够灵活，若被锁定的球员在第 1 秒就被冲开或远离了球，后 2 秒依然会僵硬地占着角色。距离迟滞：物理意义明确，反应更敏捷……劣势：若临界参数调得不合理，在特定距离下仍有抖动可能。"
