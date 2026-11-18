# 08 附录 A 补充-常见问题与优化方向

> 来源：https://booster.feishu.cn/wiki/Wvk5wo4tZioarJkkKIbcWFHcnQe（原文约 2700 字）

## 一、核心要点

**六个常见问题（原文逐条）**

1. **`set_velocity` 静默跳过**：速度指令"只有在 `mode == "walk"` 且非踢球中才真正生效"。`walk_to` 开头会 `release_kick()`，但若在 `ensure_ready()` 返回 `False`（摔倒 / 还没切到 walk 模式）时直接发速度指令，会被忽略且**不报错**——表现为"机器人原地不动，日志也平静"。排查顺序：先确认 `p.ensure_ready()` 返回 `True` 且 `p.mode == "walk"`。
2. **有人被罚下时 `players[i]` 下标错配**：`_act_ready` 若按 `players[0]`/`[1]`/`[2]` 分站位，`active` 只剩 2 人时"`players[2]` 越界或站位错配"。修复方向：用 `player.id` 而非列表下标做站位映射。
3. **死参数**：`KICK_POWER_BACKFIELD`、`GUARD_THREAT_ENTER_X`/`EXIT_X`、`CENTER_LEAVE_DIST_M`、`OPPONENT_RESTART_AVOID_M`、`CIRCLE_MARGIN_M` 等"声明了但当前代码未引用"，改它们毫无效果。排查命令：`grep -rn "参数名" src/`。
4. **预留但未用的 API**：`take_kickoff()`（开球专用走位+踢球）、`kick_can_score()`（判断某方向能否进球）、`block_path_projection()`（算自己到"对手→球"线段的垂足，封堵传球线）、`detour()`（单障碍绕行 via 点）。写新战术时优先复用，别重造。
5. **忘记在 `init_store` 初始化字段**：首次靠 `getattr(store, "xxx", None)` 兜底能跑，但后续代码若假设它是 `list` / `float`（如 `store.history.append(...)`、`store.kick_until + 0.6`）仍会崩。习惯：所有字段在 `init_store` 里集中声明 + 注释 + 初值。
6. **⚠️ `OPP_SET_PLAY` 仍在调用 `_act_normal`**：对方定位球时我方冲上去 `attack()` 抢球 → 触碰球被判罚、少打一人。原文明确："`_act_opp_set_play` 里**永远不要直接调 `_act_normal`**"，应按 `get_set_play_type` 分派到"只走位、不触球"的防守函数，"任何分支里都用 `walk_to` + `stop`，不要 `attack()`"。

**九个优化方向（原文按收益排序，称"挑 2~3 个先做就能显著提分"）**

1. **角色分配打分**：不再只看"谁离球最近"，综合到达时间、射门角度、是否被挡、体力/位置，用 `store` 记住评分做迟滞。
2. **走位与避障**：动态避障权重（球门方向优先）、队友协同让路、向前压迫的选线。
3. **射门选点**：`plan_kick()` 当前固定踢向门中心，应改为"门内最大空当 / 避开守门员"，按比分选稳妥或冒险，并用 `kick_can_score()` 校验该方向是否真能进。
4. **开球与定位球**：补全 `OUR_SET_PLAY` / `OPP_SET_PLAY` 的留白，做传切配合、假动作、二次进攻。
5. **分区与阵型**：按球所在区域压上/回收，在 `Phase` 之上再做一层战术阶段机（如 `ATTACK`/`NEUTRAL`/`DEFEND`）。
6. **参数自适应**：按比分、剩余时间、对手强度动态调 `SUPPORT_DIST_M`、`MAX_LINEAR`。
7. **守门逻辑**：增强 `guard` 的预判与出击时机，危险区主动前压断球。
8. **跨帧战术**：用 `store` 做多阶段战术（如"先佯攻左路，再转移右路"）。
9. **对手建模**：读 `opponents` 状态做速度/意图预测，提前布防。

## 二、代码与公式

**1）`OPP_SET_PLAY` 修复骨架（原文 常见问题 6，落 `src/main.py:318`）**

```python
def _act_opp_set_play(self, context, players, store) -> None:
    """对方定位球：只走位、不触球。"""
    if not players:
        return
    kind = get_set_play_type(context)
    ball = context.ball

    # 1) 先算出"必须让开"的禁区圆
    avoid_r = OPPONENT_RESTART_AVOID_M          # 1.65 m，规则线 1.45 m 留余量
    if ball is not None:
        # 2) 每台机器人的目标点 = 己方半场、距球 >= avoid_r 的最近合法点
        for p in players:
            target = _nearest_safe_point(p.pose, ball, avoid_r, context.field)
            # 3) 只走位；到点后 stop()，绝不 attack()
            p.walk_to(target, avoid_ball=True, avoid_robots=True)
```

要点（原文 + 项目约束）：**不调用 `attack()`**；`walk_to` 的目标点必须 `clamp_inside_field`；球在 3 m 内不要原地久站（10 s 无活动罚下），等待点放到 3 m 外；分支必须覆盖 `DIRECT_FREE_KICK`/`INDIRECT_FREE_KICK`/`PENALTY_KICK`/`THROW_IN`/`GOAL_KICK`/`CORNER_KICK` 全部枚举，每个分支给**所有**球员分配动作。

**2）`ensure_ready` 排查（原文 常见问题 1）**

```python
if not p.ensure_ready():          # 摔倒 / 未切 walk / 受罚
    return                        # 此时任何 set_velocity 都会被静默丢弃
assert p.mode == "walk"
p.walk_to(target, ...)
```

本仓库 `src/player.py:174 set_velocity` 自身无显式 `mode` 判断，静默丢弃发生在下游 backend/SDK，所以**必须在策略层自己判** `ensure_ready()`，不要假设"发了就一定动"。

**3）`init_store` 集中声明模板（原文 常见问题 5）**

```python
def init_store(self, store) -> None:
    store.prev_phase = None
    store.cur_phase = None
    store.kickoff_taker = None          # int | None
    store.normal_attacker = None        # int | None
    store.kick_cooldown_until = 0.0     # float，时间戳
    store.opp_set_guard_until = 0.0     # float
```

**4）`kick_can_score()` 校验射门方向（原文 常见问题 4 + 优化 3）**

```python
if p.kick_can_score(angle_to_goal_opening):
    p.kick(angle_to_goal_opening, KICK_POWER_DEFAULT)
else:
    p.kick(angle_to_safe_side, KICK_POWER_DEFAULT)
```

**5）`block_path_projection()` 封堵传球线（原文 常见问题 4 + 优化 9）**

```python
# 站在"对手 → 球"连线上，切断传球/推进路线
via = p.block_path_projection(opponent.pose, ball)
if via is not None:
    p.walk_to(via, avoid_ball=True)
```

## 三、易错点

- **【原文】** `OPP_SET_PLAY` 复用 `_act_normal`：对方定位球期间我方 `attack()` 会触球，直接吃牌少打一人。这是本仓库当前**真实存在**的缺陷（`src/main.py:318-320`）。
- **【原文】** 用列表下标分角色：`players[2]` 在少一人时越界或错配。本仓库 `src/main.py:323-385` 有 `len(players) >= n` 保护，**不会** `IndexError`，但会"少一个槽位"——站位空一格、三人阵型塌陷，属于同一类错误。
- **【原文】** 改死参数看不到效果，误判"调参无用"。
- **【原文】** 重复实现已有 API（自己写开球走位、自己算进球判定），既慢又容易违反规则。
- **【经验建议】** 本仓库的"死参数"清单与原文不完全一致：`KICK_POWER_BACKFIELD` 实际被 `src/player.py:247 plan_kick()` 引用（`_in_backfield()` 为 `ball.x < 0` 时生效），只因取值 5.0 与默认相同而"看起来无效"；而 `GUARD_THREAT_ENTER_X`/`EXIT_X`、`CENTER_LEAVE_DIST_M`、`OPPONENT_RESTART_AVOID_M`、`CIRCLE_MARGIN_M`、`OPP_SET_WALL_DIST_M` 在 `src/` 下确实零引用。写注释时务必区分"同值无效"与"未接入"。
- **【经验建议】** `walk_to` 的 `avoid_ball` 只绕开球 0.5 m，**不等于**规则避让距离 1.45 m；对方定位球阶段必须自己按 `OPPONENT_RESTART_AVOID_M = 1.65 m` 选点，不能指望避障参数兜底。
- **【经验建议】** 优化方向 5（分区阵型）会与现有 `get_phase` 冲突：不要在 `get_phase` 里塞战术态，应另设 `store.tactical_mode`（`ATTACK`/`NEUTRAL`/`DEFEND`），`Phase` 只回答裁判状态。

## 四、对本项目的具体改进建议

**A. 六个 FAQ 逐条落地**

1. **`src/main.py:318-320` 重写 `_act_opp_set_play`（最高优先级，规则违规）。** 删除对 `_act_normal` 的调用；按 `get_set_play_type(context)` 分支，每支都用 `walk_to` + 到点 `stop()`，全程不 `attack()`、不 `kick()`。新增 `src/main.py` 模块级辅助函数 `_nearest_safe_point(pose, ball, min_dist, field)`：在己方半场网格上取 `dist >= min_dist` 且 `clamp_inside_field` 内、离 `pose` 最近的点。上面的骨架只是"保命层"（保证不碰球）；`DIRECT_FREE_KICK`/`INDIRECT_FREE_KICK` 应在此基础上叠用 `10-set-play-defense.md` 的"两人人墙 + 一人守门"模板，`THROW_IN`/`CORNER_KICK` 叠用该篇的盯人/区域站位，不要只满足于"站远一点"。
   **验收**：回放对方任意球/角球，所有机器人距球始终 > 1.45 m，全场零"定位球触球"判罚，`player.action` 标签不出现 `attack`。
2. **`src/main.py:323-385` 的 `_act_ready` 改为按 id 映射。** 当前是三段 `if len(players) >= 1/2/3`，各槽位独立守卫——**不会** `IndexError`，但少一人时 `players[0]`、`players[1]` 会顶到 1、2 号槽位、3 号槽位空着，即原文说的"站位错配"。改为"`player.id` → 槽位号"的固定映射（如 `READY_SLOT_BY_ID = {1: 0, 2: 1, 3: 2}`），缺员时该槽位空缺、其余人保持原槽，不再顺次顶替。
   **验收**：手动罚下 1 人，READY 阶段另 2 台机器人仍站原槽位，不串位、不重叠。
3. **`src/player.py` / `src/main.py`：所有 `set_velocity` 调用前置 `ensure_ready()` 判断。** `Player` 内部已有 `walk_to`/`attack`/`guard` 的统一入口（`src/player.py:174` 的 `set_velocity` 本身不判 mode，见三、经验建议），重点检查策略层直接调 `p.set_velocity` 的地方（当前 src/ 下无，但要防新增），并在 `walk_to` 未返回 `True` 时**不要**假设速度已生效。
   **验收**：机器人摔倒瞬间不发速度指令，起身后自动恢复。
4. **`src/param.py`：给死参数加"未接入"注释块**，并在文件末尾附 `grep` 自查命令注释：`grep -rn "GUARD_THREAT_ENTER_X" src/`。将 `KICK_POWER_BACKFIELD` 注释改为"`plan_kick()` 在 `ball.x < 0` 时引用；与 DEFAULT 同值 5.0 故当前无差别"。
   **验收**：任何参数都有"被谁引用 / 未接入"的明确说明。
5. **`src/main.py:115 init_store`：补全所有 `store.` 字段声明**（见二、3 模板），并在 `play()` 里禁止 `getattr(store, ...)` 之外的隐式创建。
   **验收**：`grep -n "store\." src/main.py | grep -v "store\.\(prev_phase\|cur_phase\|...\)"` 无输出，即所有字段都在 `init_store` 出现。
6. **复用预留 API**：`_act_our_kickoff`（`src/main.py:257-284`）改调 `attacker.take_kickoff(kick_target)`，替换手写绕后逻辑（`take_kickoff` 已实现 `KICKOFF_STAGE_M` 退位 + `KICKOFF_FRONT_MARGIN` 前压 + `KICKOFF_LATERAL_TOL` 横向容差）；`plan_kick()`（`src/player.py:232`）里用 `kick_can_score()` 过滤候选方向。
   **验收**：我方开球成功率提升、且不违反"开球射门"规则（球离点 0.5 m 外或第二人触球后才射）。

**B. 九个优化方向逐条转成可执行项（按"投入/收益"排序，先做 1/3/7）**

1. **角色分配打分（`src/main.py:208 _select_closest_attacker`）**：把单一距离改为 `score = dist + FALLEN_COST·is_fallen + 0.5·angle_penalty`，`angle_penalty` = 该球员到"球→对方球门"连线的偏角；保留 `ATTACKER_KEEP_DIST_MARGIN_M` 迟滞。**验收**：attacker 切换次数下降 ≥50%，且不再出现"选摔倒的人"。
2. **走位与避障（`src/utils/path_planner.py` / `src/utils/obstacles.py`）**：给 A* 代价加"靠近对方球门方向"的权重项；队友让路用 `TEAMMATE_RADIUS` 之外的软约束。**验收**：进攻推进平均耗时下降，卡住（连续 >2 s 位移 <0.1 m）次数下降。
3. **射门选点（`src/player.py:232 plan_kick`）**：把固定的 `opponent_goal()` 目标改为"门线内采样 5 点，取守门员与最近对手遮挡最小、且 `kick_can_score()` 为真的点"；比分落后时放宽冒险度。**验收**：射正率/进球数提升；`plan_kick` 不再恒定输出门中心。
4. **开球与定位球（`src/main.py:303 _act_our_set_play`）**：当前所有分支都 `_act_normal`，先按 `SetPlay` 分支；`THROW_IN`/`CORNER_KICK` 用"一人主罚 + 一人接应 + 一人回防"三角站位，第一脚不朝己方球门（规则）。**验收**：定位球后 3 s 内控球率提升，零乌龙。
5. **分区与阵型（新函数 `_tactical_mode(context, store)`）**：按 `ball.x` 三段（`<-2` / `-2..2` / `>2`）输出 `DEFEND`/`NEUTRAL`/`ATTACK`，写进 `store.tactical_mode`；`_act_normal` 据此调 `SUPPORT_DIST_M` 与后卫前压线。**验收**：丢球后回收更快，不再全队压上被反击。
6. **参数自适应（`src/param.py` + `_act_normal`）**：落后且 `secs_remaining < 60` 时 `MAX_LINEAR *= 1.15`、`SUPPORT_DIST_M *= 0.8`；领先时相反。数值全部进 `param.py`（如 `ADAPT_SPEED_GAIN`、`ADAPT_SUPPORT_GAIN`）。**验收**：落后局面下前场触球次数上升。
7. **守门逻辑（`src/player.py:595 guard`）**：启用已声明未用的 `GUARD_THREAT_ENTER_X`/`EXIT_X` 做"危险区前压"迟滞（球进入 `x < -1.0` 才出击，退出 `x > -0.7` 才回位）；用 `store.ball_predict` 提前横移。**验收**：一对一单刀扑救率提升，且不出现门将跑出禁区丢空门。
8. **跨帧战术（`store`）**：加 `store.set_play_stage`（`PREP`→`EXECUTE`→`FOLLOW`）与时间戳，实现"二次进攻"：第一脚踢出后 2 s 内仍按进攻站位，而不是立刻回防。**验收**：定位球二次进攻射门次数 >0。
9. **对手建模（`src/main.py` 新增 `_predict_opponent`）**：用 `store.prev_opponents` 差分算对手速度，预判 0.3 s 后位置，守门/封堵用预判点。**验收**：封堵传球线成功率提升（`block_path_projection` 命中率）。

## 五、原文关键摘录

| # | 问题 | 原文关键句 |
|---|---|---|
| 1 | `set_velocity` 静默跳过 | "只有在 `mode == "walk"` 且非踢球中才真正生效……会被忽略而不报错——表现为'机器人原地不动，日志也平静'。" |
| 2 | 罚下后下标错配 | "`players[2]` 越界或站位错配。" |
| 3 | 死参数 | "声明了但当前代码未引用……`grep -rn "参数名" src/`。" |
| 4 | 预留 API 未用 | "`take_kickoff()`、`kick_can_score()`、`block_path_projection()`、`detour()`。" |
| 5 | 忘记 `init_store` | "首次靠 `getattr(store, "xxx", None)` 兜底……后续若假设是 `list` 仍出错。" |
| 6 | `OPP_SET_PLAY` 调 `_act_normal` | "永远不要直接调 `_act_normal`……任何分支里都用 `walk_to` + `stop`，不要 `attack()`。" |

| # | 优化方向 | 原文要点 |
|---|---|---|
| 1 | 角色分配打分 | 综合到达时间/射门角度/是否被挡，`store` 记评分做迟滞 |
| 2 | 走位与避障 | 动态避障权重、队友协同让路、压迫路线 |
| 3 | 射门选点 | 门内最大空当、避开守门员、按比分选稳妥/冒险、`kick_can_score()` 校验 |
| 4 | 开球与定位球 | 补全 `OUR/OPP_SET_PLAY` 留白、传切、假动作、二次进攻 |
| 5 | 分区与阵型 | 按球区域压上/回收，`Phase` 之上加战术阶段机 |
| 6 | 参数自适应 | 按比分/剩余时间/对手强度调 `SUPPORT_DIST_M`、`MAX_LINEAR` |
| 7 | 守门逻辑 | 增强预判与出击时机，危险区主动前压断球 |
| 8 | 跨帧战术 | `store` 多阶段战术 |
| 9 | 对手建模 | 读 `opponents` 状态做预测提前布防 |

> 原文："挑 2~3 个先做就能显著提分。"
>
> 原文（问题 6）："进入对方定位球时，我方球员会照常去 `attack()` 抢球，一旦碰到球就会被裁判机判罚下场，少打一人。"
>
> 原文（问题 6 的警示）："这条坑是实战里最容易翻车的一条——很多队伍正常拼抢很强，但一遇到对方任意球就莫名少人。请务必把 `OPP_SET_PLAY` 的"不触球"原则刻进肌肉记忆。"
>
> 原文（第 9 篇预告）："第 9 篇已给出 `OPP_SET_PLAY` 的人墙/联防模板，注意里面都只做走位、不主动踢球。"（对应本仓库 `docs/kb/course/09-set-play-attack.md` 与 `10-set-play-defense.md`：人墙模板在 10 的"两人人墙 + 一人守门"，沿射门线距球 `OPP_SET_WALL_DIST_M = 2.0 m`、两人各偏 `0.3 m`；本项目落地时请直接引用该模板，不要另起一套。）
