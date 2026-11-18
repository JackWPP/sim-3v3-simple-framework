# 使用store设计跨帧策略

这一模块我们来了解机器人的战术记忆系统，理解从开赛到终场的 `store`。有了它，你才能写出"锁定主罚者""追预测落点""射门后冷却"这类具有连续性的战术。

🎯 **学习目标**

- 理解 `store` 是跨帧记忆容器
- 分清 `Context` 与 `store` 的边界
- 会用 `init_store` 声明字段
- 掌握四种跨帧设计模式

---

## 单元1：为什么需要"记忆"？

`Context` 每帧都是**全新的**，它只告诉你这一瞬间发生了什么。但复杂的战术往往是延续的：

- "刚才谁在追球？这帧他还离球最近吗？" → 保持角色不抖。
- "3 秒前我们落后，现在还落后吗？" → 持续判断局势。
- "刚进入开球阶段，主罚者定谁？" → 只在阶段切换的瞬间选一次。
- "球正以多快的速度飞向球门？0.5 秒后会到哪？" → 预测球的去向。

设计跨帧策略必须存在一个不会被每帧重置的地方，这就是 `store`。

如果机器人每帧都失忆，它就会像一条只有 7 秒记忆的鱼：上一帧决定去追球，这一帧看到球在别处，又改主意去追别的东西，来回横跳。`store` 是球队的战术笔记本，记录重要的、需要跨帧延续的信息，下一帧接着用。拥有更多信息支持决策，就是"有状态策略"比"无状态策略"强大的根本原因。

`store` 能够从连续的帧里推算出 `Context` 本身没有告诉你的信息。比如计算球速并预测球未来的位置：`Context` 只给你"这一帧球在哪"，不给"球每秒跑几米"。但如果你在 `store` 里记下"上一帧球的位置"，再和"这一帧球的位置"做差、除以 `dt`，就能算出球速 `(vx, vy)`。有了球速，就能外推"0.5 秒后球会到哪"。

在抢点、守门、拦截传球时，这极具价值——你不是去追“球现在的位置”，而是奔向“球将要到的位置”。

---

## 单元2：理解store

`store` 是一个可以随意挂属性的空对象 `SimpleNamespace`，由框架在启动时创建，在整场比赛中存活（`runtime.py`）：

```Python
# src/framework/runtime.py
self._store = SimpleNamespace()
```

选 `SimpleNamespace` 而不是字典，因为它兼顾了“随手就能加字段”和“访问简洁”。

注意它在 `__init__` 里创建，也就是**整个 Agent 生命周期只执行一次**，这正是"跨帧存活"的物理保证。在 **`init_store(store)`** 里第一次初始化它（`src/main.py`）：

```Python
# src/main.py
def init_store(self, store) -> None:
    _log.info("init_store called")
    store.prev_phase = None       # 上一帧 phase，用于检测 phase 跳变（边沿）
    store.cur_phase = None
    store.kickoff_taker = None    # 锁定的开球主罚球员 id（每次进入开球时重选）
    store.normal_attacker = None  # 当前 attacker（带迟滞）
```

之后，每帧 `play()` 都传入**同一个**`store`（`runtime.py`），你可以随时读写它的字段。

`Context` 和 `store` 是策略里仅有的两个数据源，`Context` 是"世界告诉你的"，`store` 是"你告诉自己的"。凡是能从本帧感知直接读到的，就别往 `store` 里存（存了反而会过期）；凡是需要跨帧才能算出来或必须保持稳定的，就一定要放 `store`。

| 维度 | `Context` | `store` |
|-|-|-|
| **生命周期** | 每帧重建，用完即弃 | 整场比赛存活，只在开赛前 `init_store` 一次 |
| **可变性** | 只读（`frozen=True`，改了直接抛错） | 随便读写，字段可以随时新增 |
| **数据来源** | 框架从感知/裁判机构造，是"客观事实" | 你自己写进去的，是"主观记忆与推算" |
| **用途** | 回答"现在世界什么样" | 回答"刚才发生了什么、我之前决定了什么" |
| **典型字段** | `ball`、`teammates`、`opponents`、`game`、`now`、`dt` | `prev_phase`、`normal_attacker`、`kickoff_taker`、`prev_ball` |
| **示例（读）** | `context.ball.x` → 球现在在哪 | `store.prev_ball.x` → 球上一帧在哪 |
| **示例（写）** | ❌ 不允许（`ctx.ball.x = 1` 抛错） | ✅ `store.ball_velocity = (vx, vy)` |
| **丢失风险** | 不会（每帧新鲜构造） | 字段没在 `init_store` 声明就可能 `AttributeError` |

---

## 单元3：项目中的三个 store 使用场景

### 锁定开球主罚者（`kickoff_taker`）

```Python
# src/main.py（_act_our_kickoff 内）
active_ids = {p.id for p in players}
if store.prev_phase != Phase.OUR_KICKOFF or store.kickoff_taker not in active_ids:
    store.kickoff_taker = _select_closest_attacker(context, players).id
```

这段代码让发球队员只在必要时重新选择。要么这一帧刚刚进入开球阶段，要么原来锁定的人已经不在 `active_ids` 里（摔倒了、被罚下了，只能换人），除此之外，沿用上次选择的 `kickoff_taker`。

如果每帧都重选，在一些临界情况下，可能第 1 帧派 A 去、第 2 帧派 B 去、第 3 帧又派 A 去。比赛中，只有 10 秒钟的开球时间。选择频繁抖动，可能导致球踢不出去，最终定位球变成自由球。

### 保持当前 `attacker`（`normal_attacker`）

```Python
# src/main.py
attacker = _select_closest_attacker(
    context, players, getattr(store, "normal_attacker", None),
)
store.normal_attacker = attacker.id
```

这里把“上次的选择”作为优先选择传进选择函数，选完再写回 store，形成一个“读记忆 $\rightarrow$ 决策 $\rightarrow$ 写记忆”的闭环。选择函数内部逻辑是如果上次选的人这次仍然离球足够近（在 ATTACKER_KEEP_DIST_MARGIN_M = 0.3m 容差内），就继续用他，否则才换人。ATTACKER_KEEP_DIST_MARGIN_M就是“角色不抖”的迟滞缓冲。

### 检测阶段边沿（`prev_phase` / `cur_phase`）

```Python
# src/main.py
phase = get_phase(context)
store.prev_phase = store.cur_phase
store.cur_phase = phase
```

这段代码放在 `play()` 最开头，先把旧的 `cur_phase` 挪到 `prev_phase`，再把本帧新算的 `phase` 存进 `cur_phase`。

代码保证后面所有 `_act_*` 函数都能通过对比这两个值，判断这一帧是不是刚从别的阶段切进来的，从而触发一次性逻辑（重置战术、重新选主罚者）。`_act_our_kickoff` 正是这样判断"刚进入开球"。

---

## 单元4：用 store 算球速、预测球的位置

这是最实用的 `store` 使用技巧。把上一帧的球位置存进 `store`，和这一帧对比，计算速度；再用速度外推未来位置。

### 在 `init_store` 里准备字段

```Python
# src/main.py（在 init_store 里加）
store.prev_ball = None          # 上一帧的球位置（BallState 或 None）
store.ball_velocity = (0.0, 0.0)   # 球的线速度 (vx, vy)
store.ball_predict = (0.0, 0.0)    # 预测的未来位置
```

`prev_ball` 是上一帧观测，`ball_velocity` 是差分算出的速度，`ball_predict` 是策略直接消费的预测点。球速可以用来判断"这是一脚大力射门还是一次轻推"；速度方向则能判断"球是在朝我方门来还是在往外走"。初值给 `(0.0, 0.0)` 而不是 `None`，能省掉潜在的控制判断。

```Python
# 在 play() 拿到 store 之后、分派给 _act_* 之前插入
ball = context.ball
if ball is not None and store.prev_ball is not None and context.dt > 0:
    vx = (ball.x - store.prev_ball.x) / context.dt
    vy = (ball.y - store.prev_ball.y) / context.dt
    store.ball_velocity = (vx, vy)
    # 预测 0.5 秒后球的位置（可用于抢点/守门/拦截）
    pred_x = ball.x + vx * 0.5
    pred_y = ball.y + vy * 0.5
    store.ball_predict = (pred_x, pred_y)
# 无论本帧看没看到球，都更新"上一帧"记录，供下一帧使用
store.prev_ball = ball
```

在 `play()` 里计算预测，这段代码就是高中物理的"平均速度 = 位移 / 时间"，时间来自构造 `Context` 时计算的快照间隔 `context.dt`（通常约 1/30 秒）。

### 使用预测结果

- **抢点型进攻**：让 `attacker` 不是奔向 `ball`，而是奔向 `store.ball_predict`，提前卡在球的前进路线上；
- **守门拦截**：守门员可以根据 `store.ball_predict` 提前横向移动，堵住球将要飞向球门的路线；
- **拦截传球**：根据速度方向判断球是否正飞向己方危险区，提早进行封堵。

比赛中球持续滚动，追球永远落后一步，预测球路提前出击更有效率。人类球员就很注重"看球路、卡身位"。`store` 让机器人也能拥有预判能力。

> 此步骤可借助AI Assistant完成，参考提示词：请帮我在 src/main.py 中实现“用 store 缓存上一帧球位置、计算球速并预测未来 0.5 秒落点”的完整代码，并让 attacker 奔向预测点。

> 直接用两帧做差算出的速度会有噪声（一帧的感知误差会被放大）。进阶玩法是用 `store` 缓存最近 N 帧的球位置，做滑动平均或卡尔曼滤波，得到更平滑的球速估计。

---

## 单元5： 常用的四种 `store` 设计模式

| 模式 | 行为 | 典型字段 |
|-|-|-|
| **保持状态** | 把"当前角色/目标"存进 store，下帧复用 | `normal_attacker`、`kickoff_taker` |
| **迟滞（hysteresis）** | 存"当前选中者"，下次只在差距超过阈值时才换 | `normal_attacker` + `ATTACKER_KEEP_DIST_MARGIN_M` |
| **计数 / 冷却** | 存计数器或时间戳，达到条件才允许再行动 | `store.kick_cooldown_until` |
| **阶段边沿** | 存上一帧 phase，检测跳变触发一次性逻辑 | `prev_phase` / `cur_phase` |

### 模式一：保持状态 —— 决定一次，执行到底

**目标**：决策一旦做出，就稳定地执行下去，避免每帧推翻重来。

**场景举例：开球主罚者锁定。**中圈开球，且三个球员到球的距离相近时。如果每帧都重新算谁最近，可能会出现第 1 帧 A 最近派 A、第 2 帧 B 挪了一步变最近派 B、第 3 帧又轮到 A。结果三个人在原地都不动，开球窗口白白耗尽。如果借助 `store` 保持状态，只在进入开球阶段时选一次，把 id 记进 `store.kickoff_taker`，之后每帧保持选择这个球员，另外两个人安心跑位。这就是"决定一次，执行到底"。

**适用判断**：当你发现某个决策"结果频繁变化但代价很高"（换人要重新走位、重新绕球），就该用状态保持把它钉住。

### 模式二：迟滞 —— 该换的时候才换，不该换就别抖

**目标：**平衡“保持状态”（选了永不改）与“纯实时判断”（每帧都可能改），允许状态切换，但要求竞争者必须超出一定缓冲门槛，防止决策高频跳动。

**场景举例：**attacker身份防抖。正常拼抢阶段，1 号和 2 号球员离球的距离在 2.51m 和 2.49m 之间震荡（感知存在噪声）。如果不做迟滞，`attacker` 身份会在两人之间每帧横跳：1 号刚冲向球，下一帧身份被 2 号抢走，1 号只能掉头往回走，再下一帧又变回 1 号……两个人在场上像跳舞一样原地扭动。加上迟滞后，在任的 `attacker` 享受 0.3 米的“卫冕优势”，挑战者必须比他近 0.3 米以上才能上位，成功过滤感知噪声，稳定角色。

**适用判断：**凡是“基于连续数值比大小来做离散角色或状态选择”的地方（如谁离球更近、谁速度更快、球属于哪个区域），都必须加迟滞，否则决策必抖。

### 模式三：计数 / 冷却 —— 干完一次，歇一会儿

**目标：**防止高频控制循环（如 30Hz）对需要物理执行时间的动作进行重复、无间断的打断与重发。

**场景举例：**射门后短暂冷却，防止连踢。球员抬脚射门完成一次完整踢球动作大约需要 0.5 秒，但代码在这 0.5 秒内会跑 15 帧。如果每帧都判断“离球近，该踢”，就会连发 15 次踢球指令，导致动作被反复重启打断，机器人腿部抽搐甚至摔倒。加上冷却后，踢完立刻记录 `store.kick_cooldown_until` = context.now + 0.6，后续帧在冷却未结束前只做走位调整、不发踢球指令，保证射门动作干净利落地完成。

**适用判断：**凡是“动作本身需要物理时间完成，或刚完成需要缓冲期”的场景（如射门、起身后恢复平衡、解围后避球），都应该使用冷却机制。时间戳方式（`store.xxx_until` = now + 时长）与帧率无关，最推荐使用。

### 模式四：阶段边沿 —— 只在切换的那一瞬间做一次

**目标：**在高频重复运行的控制循环中，精准捕捉状态发生跳变的那一瞬间，触发且仅触发一次初始化或重置逻辑。

**场景举例：**刚进入开球阶段时重置战术。上一秒还在正常拼抢，`store.normal_attacker` 记着 3 号；这一秒裁判判了我方开球，Phase 切到 OUR_KICKOFF。此时你需要做几件“一次性”的事：清空 NORMAL 阶段的残留状态、重新挑选开球主罚者、重置站位计划。通过对比 `store.prev_phase` 与 `store.cur_phase`，就能捕获到“切换发生的那一帧”，确保初始化逻辑只跑一次。

**适用判断：**任何需要表达“当某事件刚开始 / 阶段刚切换时，执行一次……”的需求，都属于边沿模式（例如阶段转换时的 \_clear_normal_sticky(store) 重置动作）。

---

## 🧪 章节练习

1. 用 store 实现"追球者一旦选定，3 秒内不切换"。

参考代码：

```Python
# 在 init_store 里加：
store.attacker_id = None
store.attacker_since = None     # 用 context.now 记时间戳

# 在 _act_normal 里替换选 attacker 的逻辑：
now = context.now
if (store.attacker_id is not None
        and now - (store.attacker_since or 0) < 3.0):
    attacker = next(p for p in players if p.id == store.attacker_id)
else:
    attacker = _select_closest_attacker(context, players)
    store.attacker_id = attacker.id
    store.attacker_since = now
```

> 这是"状态保持 + 冷却"两种模式的组合：`attacker_id` 存住选择结果（状态保持），`attacker_since` 存住选择时刻，配合 `now - since < 3.0` 形成一个 3 秒的换人冷却期。`(store.attacker_since or 0)` 是个小技巧，防止时间戳为 `None` 时相减报错。

1. 思考“3 秒时间锁定”与“基于距离的迟滞”相比，各有什么优劣？

> 参考答案：
> 
> 时间锁定：实现极简单，能彻底杜绝高频震荡。劣势：不够灵活，若被锁定的球员在第 1 秒就被冲开或远离了球，后 2 秒依然会僵硬地占着角色。
> 
> 距离迟滞：物理意义明确，反应更敏捷，贴合场上实际局势。劣势：若临界参数调得不合理，在特定距离下仍有抖动可能。

> 此步骤可借助AI Assistant完成，参考提示词：请帮我实现“追球者一旦选定，3 秒内不切换”的 store 逻辑，参考上述 attacker_id + attacker_since 代码，并补上 init_store 中的字段声明。

---

## 📖 扩展阅读

- [**有限状态机 Wikipedia**](https://en.wikipedia.org/wiki/Finite-state_machine)
- [**Python** ](https://docs.python.org/3/library/types.html#types.SimpleNamespace)[**`SimpleNamespace`**](https://docs.python.org/3/library/types.html#types.SimpleNamespace)[ **文档**](https://docs.python.org/3/library/types.html#types.SimpleNamespace)

---

## 📌 要点总结

- `store` 是战术笔记本，整场比赛存活，用于存储跨帧状态；
- `Context`（客观）与 `store`（主观）职责分离；
- 利用两帧位置差计算球速，预测球未来的位置；
- 基于 `store` 的四个设计模式：保持状态、迟滞、冷却、阶段边沿。