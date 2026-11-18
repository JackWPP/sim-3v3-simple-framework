# 07 参数调优

> 来源：https://booster.feishu.cn/wiki/HoJTwad7xivvC8kOp7tcdyC4npe（原文约 4900 字）

## 一、核心要点

- 全项目可调数值集中在 `src/param.py`，`main.py` / `player.py` 顶部用 `from .param import *` 一次性注入，策略里直接写 `MAX_LINEAR`、`KICK_POWER_DEFAULT`。改一处，所有引用处生效。
- 集中管参的收益：策略优化会反复改写 `main.py` / `player.py`，数字散落时调参变成"全文搜索 + 逐处替换"，极易漏改；集中后数值只有一份，`main.py` / `player.py` 只是引用者。
- 判断标准：**改策略时新引入的可变数值，也应归 `param.py` 管**；不要留在策略函数里当魔法数字。
- 原文速查表按 6 组分类：踢球力度、走位控制、射门追球、守门支援、角色/开球站位、避障路径。三组"最常调"的是 `MAX_LINEAR`、`KICK_POWER_DEFAULT`、`SUPPORT_DIST_M`，第四组是 `KICK_ENTER_M`/`KICK_EXIT_M`。
- 新手优先调这四个（原文明确排序）：
  1. `MAX_LINEAR = 2.0 m/s`：跑得够不够快，最直接；太大易失控/摔倒。
  2. `KICK_POWER_DEFAULT = 5.0`：射门力度；太软够不着门，太猛踢飞或自己摔。
  3. `SUPPORT_DIST_M = 3.0 m`：支援站位松紧，决定阵型攻守平衡。
  4. `KICK_ENTER_M` / `KICK_EXIT_M = 2.0 / 2.5 m`：追球迟滞，决定进攻稳定性（必须 `EXIT > ENTER`）。
- `KICK_POWER_MIN/MAX = 1.0/10.0` 是硬夹取范围（`Player.kick()` 内部 clamp），超出接口支持范围会摔倒，不要指望调大上限获得更猛的射门。
- 走位是 P 控制：`vx = clamp(LINEAR_GAIN * distance * cos(角差), 0.0, MAX_LINEAR)`，`vyaw = clamp(ANGULAR_GAIN * 角差, ±MAX_ANGULAR)`。`LINEAR_GAIN = 1.5` 越大越"冲"，过大会过冲震荡；`ANGULAR_GAIN = 2.0` 过大会左右摆头。两者本质是比例（P）增益，原文明确建议按 PID 的理解去调。
- `OMNI_DIST = 1.0 m`：小于该距离切全向行走（近距微调），大于则"转身—走—转身"；`TURN_THRESHOLD = 0.5 rad` 是远距行走时"先原地转身再走"的角差阈值。
- `ARRIVE_DIST = 0.15 m` 是"已到达"阈值，太大会提前停、太小会原地微调。
- `CHASE_BEHIND_M = 0.35 m` 决定追球时站到球后多远的点，直接影响射门朝向；`GOAL_TARGET_DEPTH_M = 0.25 m` 是射门目标点在门线后的深度（`opponent_goal` 用它，避免球压线时反向瞄准）。
- 调参方法论五步（原文 单元3）：
  1. **控制变量，一次只改一个**；强耦合的参数（如 `KICK_ENTER_M` 与 `KICK_EXIT_M`）当一组一起动，但仍只动这一组。
  2. **先提假设再动手**：好假设必须包含"现象、归因、预期变化"，例："球总停在门前 1 m，我认为是 `KICK_POWER_DEFAULT` 太小，5.0 → 6.5 应能越过门线"。
  3. **多尝试、记录数据**：不同局面（开球、界外球、混战、被压制）表现可能相反；用可复述的现象记录，如"射门 6 次，3 次越过门线，2 次踢偏摔倒"。
  4. **做对照**：改动前（对照组）与改动后（实验组）在同一场景各跑几次；仿真的价值就是可重复。
  5. **不生效就回滚**：没有明显优于对照组就改回去；参数堆积是最大隐形成本（"跑十轮后 param.py 里躺着七个'可能有用'的数字"）。
- 省时间技巧：**先用大步长扫出大致区间，再在最优点附近用小步长测试**。
- 原文点名"死参数"：`KICK_POWER_BACKFIELD`（与默认同值 5.0）、`GUARD_THREAT_ENTER_X`/`EXIT_X`（"受威胁"判定，未被引用）；改动它们看不到效果，容易误以为"调参没用"。

## 二、代码与公式

**1）注入方式（原文 单元1）**

```python
# src/main.py / src/player.py 顶部
from .param import *
```

**2）速度控制（`src/player.py:461-485`，原文 走位控制组）**

```python
# 近距离：全向行走
vx = LINEAR_GAIN * (wdx * cos_t + wdy * sin_t)
vy = LINEAR_GAIN * (-wdx * sin_t + wdy * cos_t)
speed = math.hypot(vx, vy)
if speed > MAX_LINEAR:                    # 等比缩放，保持方向
    vx *= MAX_LINEAR / speed
    vy *= MAX_LINEAR / speed
vyaw = clamp(ANGULAR_GAIN * err, -MAX_ANGULAR, MAX_ANGULAR)

# 远距离：转身—走—转身
if abs(angle_err) > TURN_THRESHOLD:
    set_velocity(0.0, 0.0, clamp(ANGULAR_GAIN * angle_err, -MAX_ANGULAR, MAX_ANGULAR))
else:
    vx = clamp(LINEAR_GAIN * distance * math.cos(angle_err), 0.0, MAX_LINEAR)
    set_velocity(vx, 0.0, clamp(ANGULAR_GAIN * angle_err, -MAX_ANGULAR, MAX_ANGULAR))
```

**3）好假设的写法（原文 单元3 第二步）**

```text
现象：球总停在门前 1 米处
归因：KICK_POWER_DEFAULT 太小（5.0 不足以让球滚过门线）
预期：5.0 → 6.5 后，射门能越过门线
```

跑完记录："射门 6 次，3 次越过门线，2 次踢偏摔倒"。

**4）症状 → 参数定位（原文 章节练习）**

```text
机器人总在己方禁区乱撞门柱
  → BALL_OBSTACLE_RADIUS / SAFETY_MARGIN 太小？
  → SUPPORT_DIST_M 让它站得太靠近门？
  → GUARD_FACE_BALL 站位逻辑问题？

到了球边却总踢不进、球软绵绵停在门前
  → KICK_POWER_DEFAULT 太小？
  → KICK_ENTER_M 太大，还没够近就开始踢（踢空）？
  → CHASE_BEHIND_M 站位不对导致踢偏？
```

## 三、易错点

- **【原文】** 同时改五个参数（力度 5→8、速度 2→3、支援 3→2）跑一场赢了，却不知道是哪个起了作用，甚至可能是三个改动互相抵消后靠运气赢的；场景一变全盘失灵。
- **【原文】** 不看对照组就下结论，分不清"参数变好了"还是"这局对手恰好失误"。
- **【原文】** 参数只增不减：十轮后 `param.py` 里堆着七个"可能有用"的数字，污染后续实验与 Vibe Coding 上下文。
- **【原文】** 改了死参数（`KICK_POWER_BACKFIELD`、`GUARD_THREAT_ENTER_X/EXIT_X`）却以为调参无效。
- **【原文】** `KICK_ENTER_M ≥ KICK_EXIT_M` 会破坏迟滞，边界抽搐（第 5 篇已述）。
- **【经验建议】** `param.py` 的常量被**函数默认参数**在 import 时求值绑定：`def walk_to(..., arrive_dist: float = ARRIVE_DIST)`、`def kick(..., power: float = KICK_POWER_DEFAULT)`。运行时改 `param.ARRIVE_DIST` 不会改变已绑定的默认值；要么改文件后重启，要么调用点显式传参（`p.walk_to(t, arrive_dist=ARRIVE_DIST)`）。正确做法是改 `param.py` 源文件，不要指望热改模块属性。
- **【经验建议】** 本仓库实际引用情况与原文不完全一致：`KICK_POWER_BACKFIELD` 在 `src/player.py:247` 被 `plan_kick()` 引用（`_in_backfield()` 为真时用它，当前值 5.0 与默认相同，所以"改了没效果"是**同值**导致，不是没引用）；而 `GUARD_THREAT_ENTER_X/EXIT_X`、`CENTER_LEAVE_DIST_M`、`OPPONENT_RESTART_AVOID_M`、`CIRCLE_MARGIN_M`、`OPP_SET_WALL_DIST_M` 在 `src/` 下确实无引用（`grep -rn "参数名" src/` 确认）。调参前必须先 grep。
- **【经验建议】** 调参不要动 `PLAN_*` / `GLOBAL_*` 与 `MAX_LINEAR` 一起调：它们分别控制"避障选向"和"执行速度"，同时改会让走位问题无法归因。

## 四、对本项目的具体改进建议

1. **`src/param.py`：把策略里的硬编码数字收编。** 现存散落数字（已核对）：
   - `src/main.py:297` `_act_opp_kickoff` 的 `slots = [(-r - 0.5, 0.0), (-r - 2.0, 0.5)]` → 新增 `OPP_KICKOFF_SLOT_A = (-0.5, 0.0)`、`OPP_KICKOFF_SLOT_B = (-2.0, 0.5)`（相对中圈半径的偏移，注明"单位 m，相对 `circle_radius`"）。
   - `src/main.py:323-385` `_act_ready` 的 `-field.circle_radius - 0.5`、`circle_radius + 2`、`-0.5` → 新增 `READY_BACKOFF_M = 0.5`、`READY_WIDE_M = 2.0`。
   - `src/main.py:273` `_act_our_kickoff` 的 `attacker.kick(0.1, ...)` → 新增 `KICKOFF_KICK_DIR = 0.1`（rad）。
   - `src/player.py:646` `support()` 的 `0.3` 边距 → `SUPPORT_EDGE_MARGIN_M = 0.3`。
   - `src/player.py:402` `walk_to` 到达后转向的 `0.1` 阈值 → `FACE_TOL_RAD = 0.1`。
2. **`src/param.py`：给每组参数补"影响/调大调小后果/是否被引用"注释。** 特别是目前注释为空的 `KICK_POWER_BACKFIELD`（说明它与默认同值、`_in_backfield()` 触发条件为 `ball.x < 0`）、`GUARD_THREAT_ENTER_X/EXIT_X`（标注"当前未引用，见 05 改进 1 启用"）、`CENTER_LEAVE_DIST_M` / `OPPONENT_RESTART_AVOID_M` / `CIRCLE_MARGIN_M` / `OPP_SET_WALL_DIST_M`（标注"预留，未接入"）。
3. **按原文优先级做一轮基线调参（一次只改一个，各跑 3 局对照）：**
   - `MAX_LINEAR`：2.0 起，步长 0.2，上限建议 2.6；观察是否出现急停摔倒/过冲。
   - `KICK_POWER_DEFAULT`：5.0 → 6.5（原文示例假设），记录"射门 6 次过线几次"；`KICK_POWER_MIN` 不动。
   - `SUPPORT_DIST_M`：3.0 起，2.0 / 2.5 / 3.5 三档对比阵型松紧与丢球后的反抢距离。
   - `KICK_ENTER_M`：若出现"到了球边踢空"，从 2.0 降到 1.6~1.8，同时保持 `KICK_EXIT_M ≥ KICK_ENTER_M + 0.4`。
4. **`src/param.py`：把 `KICK_POWER_BACKFIELD` 与 `KICK_POWER_DEFAULT` 解耦验证。** 现在两者都是 5.0，`_in_backfield()` 的判断（`ball.x < 0`）实际上无效果；建议后场解围设 `KICK_POWER_BACKFIELD = 6.5~7.0`，让"后场大脚"真正区别于前场推射，并用注释写清"值相同=无效"。
5. **`src/player.py:419` 避障参数只在"绕不过去"时调。** `GLOBAL_GRID_RESOLUTION_M = 0.35` 越小越细但越慢（30 Hz 每帧 3 台 × A*）；若出现卡顿优先回退 `USE_GLOBAL_PATH_PLANNER = False` 对比，而不是盲目减小栅格。`SAFETY_MARGIN = 0.22` 是通用余量，调大会绕更远、更容易被逼到边线。
6. **`src/param.py` 末尾加一段"调参记录"注释块**（日期 / 参数 / 旧值→新值 / 假设 / 结果 / 是否保留），把原文"不生效就回滚"的纪律固化到文件里；这比口头约定更能防止参数堆积。

## 五、原文关键摘录

| 分组 | 参数 | 默认值 | 影响 |
|---|---|---|---|
| 踢球力度 | `KICK_POWER_MIN` / `KICK_POWER_MAX` | 1.0 / 10.0 | 踢球力度的夹取范围，超范围易摔倒 |
| 踢球力度 | `KICK_POWER_DEFAULT` | 5.0 | 普通比赛射门力度（最常调） |
| 踢球力度 | `KICK_POWER_BACKFIELD` | 5.0 | 后场踢球力度（当前等于默认值，属死参数） |
| 踢球力度 | `KICK_POWER_OUR_KICKOFF` | 5.0 | 我方开球踢出力度 |
| 走位控制 | `ARRIVE_DIST` | 0.15 m | 认为"已到达"的阈值，太大会提前停 |
| 走位控制 | `OMNI_DIST` | 1.0 m | 小于此距离切换全向行走（近距微调） |
| 走位控制 | `TURN_THRESHOLD` | 0.5 rad | 远距行走时"先转身再走"的角差阈值 |
| 走位控制 | `MAX_LINEAR` | 2.0 m/s | 前进速度上限（最直接的速度旋钮） |
| 走位控制 | `MAX_ANGULAR` | 2.0 rad/s | 转向速度上限 |
| 走位控制 | `LINEAR_GAIN` | 1.5 | 平移 P 增益（越大越"冲"，过大会震荡） |
| 走位控制 | `ANGULAR_GAIN` | 2.0 | 转向 P 增益（过大会左右摆头） |
| 射门追球 | `KICK_ENTER_M` | 2.0 m | 距球多近进入踢球状态 |
| 射门追球 | `KICK_EXIT_M` | 2.5 m | 踢球中距球多远才退出（迟滞上限） |
| 射门追球 | `CHASE_BEHIND_M` | 0.35 m | 追球时站到球后方的距离，影响射门朝向 |
| 射门追球 | `GOAL_TARGET_DEPTH_M` | 0.25 m | 射门目标点设在门线后方多深 |
| 守门支援 | `GUARD_FACE_BALL` | True | 守门员是否始终面向球 |
| 守门支援 | `GUARD_THREAT_ENTER_X` / `EXIT_X` | -1.0 / -0.7 | 守门"受威胁"判定的 x 区间（死参数） |
| 守门支援 | `SUPPORT_DIST_M` | 3.0 m | 支援站位距球距离（决定阵型松紧） |
| 角色/开球站位 | `ATTACKER_KEEP_DIST_MARGIN_M` | 0.3 m | attacker 切换的迟滞容差，防角色抖动 |
| 角色/开球站位 | `FALLEN_COST` | 10.0 m | 摔倒球员的距离惩罚（避免选摔倒的人） |
| 角色/开球站位 | `KICKOFF_STAGE_M` | 2.0 m | 开球站位退后的距离 |
| 角色/开球站位 | `KICKOFF_FRONT_MARGIN` | 0.1 m | 开球"已在球后"的前向容差 |
| 角色/开球站位 | `KICKOFF_LATERAL_TOL` | 0.35 m | 开球横向容差 |
| 角色/开球站位 | `CENTER_LEAVE_DIST_M` | 0.15 m | 球离中心多远算"球已经动了" |
| 角色/开球站位 | `OPP_SET_WALL_DIST_M` | 2.0 m | 对方定位球时人墙距球的阻挡距离 |
| 角色/开球站位 | `OPPONENT_RESTART_AVOID_M` | 1.65 m | 对方重开球时必须让开的半径 |

| 避障路径 | 默认值 | 说明 |
|---|---|---|
| `BALL_OBSTACLE_RADIUS` | 0.5 m | 球作为障碍的半径（防止走位撞球犯规） |
| `OPPONENT_RADIUS` / `TEAMMATE_RADIUS` | 0.55 / 0.48 m | 对手 / 队友的机器人障碍半径 |
| `SAFETY_MARGIN` | 0.22 m | 通用安全余量，越大绕得越远 |
| `USE_GLOBAL_PATH_PLANNER` | True | 是否用 A*（False 退回局部 VFH） |
| `GLOBAL_GRID_RESOLUTION_M` | 0.35 m | A* 栅格精度（越小越细、越慢） |
| `PLAN_LOOKAHEAD` | 1.2 m | 局部避障向前"看"多远 |
| `PLAN_CLEARANCE` | 0.35 m | 候选方向前方必须留出的最小余量 |
| `PLAN_STEP` / `PLAN_MAX_OFFSET` | 15° / 100° | 局部避障扫描的步长 / 范围 |

> 原文："很多同学的调参过程是这样的：觉得踢不进 → 把力度从 5 改到 8 → 顺手把速度也从 2 改到 3 → 再把 `SUPPORT_DIST_M` 缩到 2 → 跑一场，赢了。然后就陷入了迷茫，你不知道是哪一个改动起了作用。"
>
> 原文："参数堆积是调参最大的隐形成本：跑十轮之后 `param.py` 里躺着七个'可能有用'的数字，可能污染任何新实验和 Vibe Coding 上下文。"
>
> 原文："先用大步长扫出大致区间，再在最优点附近用小步长测试。"
