# 04 使用 Context 判断比赛动态
> 来源：https://booster.feishu.cn/wiki/MfXNwA1wziqAScke8RzckI9pnwh（原文约 7.1k 字）

## 一、核心要点

- `Context` 是**框架每帧构造的只读快照**，作为 `play()` 的第一参数传入，在 `src/framework/types.py` 定义，标注 `@dataclass(frozen=True)`。
- **不可变是硬约束**：`ctx.ball.x = 1` 会直接抛错——"感知数据是事实，策略只能读取事实、再决定动作，而不能篡改事实"。**所有战术记忆写进 `store`**。
- `Context` 七组字段：`now`/`dt`（时间）、`team_id`（身份）、`field`（静态场地）、`game`/`ball`/`teammates`/`opponents`（动态观测）。
- `game` / `ball` / 每个 `RobotState.pose` **都可能为 `None`**，用前必须判空。
- `RobotState` 把"是谁"（`player_id`）和"他在哪"（`pose`，可为 `None`）拆开；位姿未知时 `pose=None`。
- `BallState` 除 `x`/`y` 外还有 `last_seen_at`（上次观测时间）与 `confidence`（视觉确信度），原文说明这两个字段"主要用于视觉辅助定位"。
- `GameControlState` 是**状态机判定 Phase 的唯一依据**，关键字段：`stopped`、`state`（`INITIAL`/`READY`/`SET`/`PLAYING`/`FINISHED`）、`set_play`（`NONE`/`CORNER_KICK`/`THROW_IN`/…）、`kicking_team`（**`255` 表示"没有指定主罚方"**）、`secs_remaining`、`secondary_time`（开球/定位球倒计时窗口）、`teams`（每队 `TeamState`，含 `score`）。
- **坐标系（队伍视角，全篇最关键约定）**：
  - **+x 朝对方球门，-x 朝己方球门，场地中心 `(0,0)`**；
  - `theta=0` 表示机器人面朝 `+x`（即面朝对方门）；
  - `opponent_goal(ctx)` 返回 **`(field.length/2 + 深度, 0)`** —— 对方球门中心（深度即 `GOAL_TARGET_DEPTH_M`）；
  - `own_goal(ctx)` 返回 **`(-field.length/2, 0)`** —— 己方球门中心；
  - 仿真环境执行策略时**自动转换坐标系**，"你只需要写一套'往 +x 方向进攻'的逻辑"。
- 场地尺寸 `ADULT_FIELD_DIMENSIONS`（`types.py`）：`length=14.0`、`width=9.0`、`goal_width=2.6`、`circle_radius=1.5`、`penalty_area_length=3.0`、`penalty_area_width=6.0`、`goal_area_length=1.0`、`goal_area_width=4.0`、`penalty_dist=2.1`。
- 由此推出的常量：**己方球门在 `x=-7.0`，对方球门在 `x=+7.0`**（`length/2 = 7.0`）；**中圈半径 1.5 m**，即开球点 1.5 m 内是对方开球时不能进入的区域。
- 解析套路（原文的通用方法）：**战术意图 → 读哪些字段 → 算出判据 → 调哪个动作**；"很多'球出没出界''对方是否进入危险区'的判断，本质都是拿 `ball.x/ball.y` 和这些尺寸做比较"。
- `closest_player_to_ball` 的三点关键：**① 先判 `ball is None`**，宁可返回 `None` 让上层走保守分支；**② 跳过不可用球员**（`pose is None` / `is_penalized`）；**③ 给摔倒者加 `FALLEN_COST`（10 米）惩罚**——"他物理上确实离球最近，但爬起来要好几秒"。
- 原文对这种写法的评价：**"用代价函数代替硬规则"**很好扩展——想让守门员优先留守，给他也加个惩罚项即可。

## 二、代码与公式

### 2.1 `Context`（原文 单元1，`src/framework/types.py`）

```python
@dataclass(frozen=True)
class Context:
    now: float
    dt: float
    team_id: int
    field: FieldDimensions
    game: GameControlState | None = None
    ball: BallState | None = None
    teammates: dict[int, RobotState] = field(default_factory=dict)
    opponents: dict[int, RobotState] = field(default_factory=dict)
```

### 2.2 四个基础类型（原文 单元2）

```python
@dataclass(frozen=True)
class Pose2D:
    x: float = 0.0
    y: float = 0.0
    theta: float = 0.0     # 朝向角（弧度），0 表示朝 +x

@dataclass(frozen=True)
class BallState:
    x: float = 0.0
    y: float = 0.0
    last_seen_at: float = 0.0     # 上次观测到球的时间
    confidence: float = 1.0

@dataclass(frozen=True)
class RobotState:
    player_id: int
    pose: Pose2D | None = None     # 位姿未知时为 None
    last_seen_at: float = 0.0

@dataclass(frozen=True)
class GameControlState:
    stopped: bool = False
    state: GameState = GameState.INITIAL          # INITIAL/READY/SET/PLAYING/FINISHED
    set_play: SetPlay = SetPlay.NONE              # NONE/CORNER_KICK/THROW_IN/...
    first_half: bool = True
    kicking_team: int = KICKING_TEAM_NONE         # 255 表示"没有指定主罚方"
    secs_remaining: int = 0
    secondary_time: int = 0                       # 开球/定位球倒计时窗口
    teams: tuple[TeamState, ...] = ...            # 每队一个 TeamState，含 score
```

### 2.3 带惩罚项的最小值搜索（原文 单元5，"可直接粘贴使用"）

```python
# src/main.py —— 可直接粘贴使用
from .utils.geom import dist
from .param import FALLEN_COST     # 摔倒球员的距离惩罚（米）

def closest_player_to_ball(context, players):
    """返回离球最近、且本帧能动的 Player；无法判断时返回 None。"""
    ball = context.ball
    if ball is None:
        return None                          # ① 看不到球 → 明确返回"不知道"

    best, best_cost = None, float("inf")
    for p in players:
        if p.pose is None or p.is_penalized:
            continue                         # ② 位置未知 / 被罚下 → 不参与竞争
        cost = dist(p.pose.x, p.pose.y, ball.x, ball.y)
        if p.is_fallen:
            cost += FALLEN_COST              # ③ 摔倒的人"看起来近"，但实际慢
        if cost < best_cost:
            best, best_cost = p, cost
    return best
```

### 2.4 常用判据（原文 单元5 的表，可直接抄进 `_act_*`）

| 战术意图 | 读哪些字段 | 怎么算（判据） |
|---|---|---|
| 球在我方半场就回收 | `context.ball.x` | `ball.x < 0` |
| 支援球员回撤保护 | `context.teammates` + 角色分派 | 挑本帧被派为 support 的那个 `Player` |
| 谁去追球（选 attacker） | `context.ball` + 各 `p.pose` | 到球距离最小者（摔倒者加惩罚） |
| 球进入我方危险区 | `ball.x/y` + `context.field` | `ball.x < -4.0` 且 `|ball.y| < 3.0` |
| 比分落后要压上 | `context.game.teams[].score` | 我方 score < 对方 score |
| 剩余时间不多 | `context.game.secs_remaining` | `< 60` |
| 现在是我方开球 | `game.secondary_time`、`kicking_team` | `secondary_time > 0` 且 `kicking_team == team_id` |
| 对方定位球要退开 | `game.set_play`、`kicking_team` | `set_play != NONE` 且 `kicking_team != team_id` |
| 对手压进我方禁区 | `context.opponents[].pose` | 统计 `pose.x < -4.0` 的对手数 |
| 球丢了看不见 | `context.ball` | `ball is None` |
| 机器人摔倒/被罚 | `p.is_fallen` / `p.is_penalized` | 布尔判断 |

### 2.5 场地尺寸（原文 单元4，`types.py` 的 `ADULT_FIELD_DIMENSIONS`）

```python
length=14.0, width=9.0, goal_width=2.6, circle_radius=1.5,
penalty_area_length=3.0, penalty_area_width=6.0,
goal_area_length=1.0, goal_area_width=4.0, penalty_dist=2.1
# 派生：己方球门 x=-7.0，对方球门 x=+7.0
```

## 三、易错点

- 【原文】**试图修改 `Context`**：`frozen=True`，赋值直接抛错；记忆必须落 `store`。
- 【原文】**不判 `ball is None` 就取 `ball.x`**：球丢了（视觉丢失）时会崩或读到脏值；正确做法是上层走保守分支。
- 【原文】**用绝对坐标系思考**：策略里"对方球门永远在 +x、自家球门永远在 -x"，平台已自动转换；自己再做左右镜像会反向瞄准。
- 【原文】**用硬编码坐标代替 `field` 字段**：场地尺寸在 `context.field`，写死 `7.0`、`-7.0`、`1.5` 会在换场地/换组别时失效。
- 【原文表内自相矛盾】危险区判据两处不一致：单元 4 正文写 `ball.x < -penalty_area_length`（= **-3.0**），**漏了 `length/2` 项**；单元 5 的表写 `ball.x < -4.0`。严格按 `field` 推导应为 `-length/2 + penalty_area_length` = **-7.0 + 3.0 = -4.0**，即**己方大禁区线**——所以表里的 -4.0 才是对的，正文的 -3.0 是省略写法，两者差 1 m。改代码时用 `-length/2 + penalty_area_length` 推导，不要抄 -3.0。
- 【原文】**把 `kicking_team` 只当普通整数比大小**：它的特殊值是 `255`（`KICKING_TEAM_NONE`），"没有人主罚"必须单独排除，否则 `!= team_id` 会被误判成"对方主罚"。
- 【原文代码 vs 本项目类型】表里"读 `context.game.teams[].score`"在本项目要配合 **`TeamState.team_number`** 而不是 `team_id`；用 `game.get_team_state(context.team_id)` 最稳（`src/framework/types.py` 已提供该方法）。
- 【原文代码 vs 本项目现状】原文的 `closest_player_to_ball` **没有迟滞**：每帧纯取最小，两人距离接近时会来回换 attacker。本项目 `src/main.py:_select_closest_attacker` 已用 `ATTACKER_KEEP_DIST_MARGIN_M = 0.3` 做迟滞，**合并两者才是正确做法**。
- 【原文代码 vs 本项目现状】原文函数名是 `closest_player_to_ball`，本项目实际叫 `_select_closest_attacker`（`src/main.py:208`）；直接粘贴同名函数不会生效，因为 `_act_normal` 只调后者。
- 【经验建议】**把 `teammates` 的 key 当作球员编号顺序**：它是 `dict[id, RobotState]`，遍历顺序不保证与 `players` 列表一致；需要"第 N 个球员"时用 `players` 列表，不要用 `teammates` 下标。

## 四、对本项目的具体改进建议

1. **`src/utils/geom.py` 补三个纯函数**（原文"本质都是拿 `ball.x/ball.y` 和尺寸做比较"的直接落地）：

```python
def in_own_penalty_area(ctx, x, y) -> bool:
    return (x < -ctx.field.length / 2.0 + ctx.field.penalty_area_length
            and abs(y) < ctx.field.penalty_area_width / 2.0)

def in_own_goal_area(ctx, x, y) -> bool:
    return (x < -ctx.field.length / 2.0 + ctx.field.goal_area_length
            and abs(y) < ctx.field.goal_area_width / 2.0)

def in_center_circle(ctx, x, y) -> bool:
    return dist(x, y, 0.0, 0.0) < ctx.field.circle_radius
```

   理由：现在 `_act_opp_kickoff`、`_act_ready` 各自用 `circle_radius` 手算，`player.py:_in_backfield` 直接 `return ball.x < 0`（注释里还留着被注释掉的 `penalty_area_length` 版本），口径不统一。

2. **`src/main.py:_player_dist_to_ball`（`src/main.py:195-201`）**：球不可见时对所有球员返回 `math.inf`，`min()` 会退化成"取列表第一个"，等于随机选人。建议改为在 `_select_closest_attacker` 开头显式处理：

```python
if context.ball is None:
    return players[0]                      # 明确回退：保持上一帧角色，别随机换
```

   或在 `play()` 里球为 `None` 时直接让 3 人 `move_to_position` 回到防守站位（**经验建议**）。

3. **`src/main.py:_act_normal`**：加"危险区优先解围"子分支，用 `in_own_penalty_area(context, ball.x, ball.y)` 判断；命中时 `support` 不再站 `SUPPORT_DIST_M = 3.0` 的封堵线，而是回收小禁区前沿 `(-field.length/2 + field.goal_area_length + 0.5, ±1.0)`，并要求 `attacker` 往边路踢（`p.attack(kick_target=...)` 传边线方向而不是默认的球门中心）。

4. **`src/main.py` 新增 `count_opponents_in_our_box(context)`**：`sum(1 for r in context.opponents.values() if r.pose is not None and r.pose.x < -context.field.length/2 + context.field.penalty_area_length)`，用于"对手压进我方禁区"的判据；超过 2 人时全员回收。

5. **`src/param.py` 新增**：`TIME_LOW_SECS = 60`、`BOX_RECOVER_X_M = 1.5`、`BOX_RECOVER_Y_M = 1.0`、`KEEPER_COST = 2.0`。**危险区不设坐标常量**——一律用第 1 条的 `in_own_penalty_area(context, x, y)`，它由 `context.field` 推导（`x < -length/2 + penalty_area_length` = -4.0，`|y| < penalty_area_width/2` = 3.0），换场地尺寸自动跟随，不会像原文正文那样把 `-penalty_area_length` 误当成 -3.0。所有阈值集中在此，`main.py` 用 `from .param import *` 直接可用。

6. **`src/main.py:_select_closest_attacker`**：把惩罚项从"只有摔倒"扩展为可配置的**代价列表**——`FALLEN_COST`（已有）、`KEEPER_COST`（门将候选加 2.0 m，避免门将弃门追球）、`BEHIND_BALL_COST`（球在对方半场时，位置靠后的球员额外加代价）。这与原文"用代价函数代替硬规则"完全一致，且只需改一个函数。

7. **`src/main.py:_analyze_and_draw`**：把原文表的判据可视化——在球上方画 `danger=1/0`、在 phase 标签行追加 `secs=… score=…`，赛场复盘时不用翻日志（**经验建议**）。

## 五、原文关键摘录

> 状态机的每一次判断，都要有"看得见的世界"作依据。这个世界就是 `Context`，它是框架每帧递到你手里的只读快照。

> `Context` 标注了 `@dataclass(frozen=True)`（types.py），意味着它是不可变的。你不能在 `play()` 里修改它（`ctx.ball.x = 1` 会直接抛错）。因为感知数据是事实，策略只能读取事实、再决定动作，而不能篡改事实。所有战术记忆应该写进 `store`。

| 字段 | 含义 | 你能拿它做什么 |
|---|---|---|
| `now` / `dt` | 当前时间 / 距上一帧的时间差（秒） | 算速度、做"每 N 秒触发一次"的节奏控制 |
| `team_id` | 我方队伍编号（1 或 2） | 区分主客队视角、读取对应队伍比分 |
| `field` | 场地尺寸（长度、宽度、球门宽…） | 所有"出界/危险区"判断的物理边界 |
| `game` | 裁判机状态（比分、阶段、定位球类型…） | 决定 Phase、读比分、判断谁主罚 |
| `ball` | 球的位置/置信度 | 追球、射门、判断归属的核心数据（可能 `None`） |
| `teammates` | 我方球员位姿，键是球员 id（1..3） | 分派角色、算谁离球近 |
| `opponents` | 对方球员位姿，键是球员 id | 避障、判断威胁、对手建模 |

| 参数 | 值 | 含义 |
|---|---|---|
| `length` | 14.0 m | 场地长（沿 x） |
| `width` | 9.0 m | 场地宽（沿 y） |
| `goal_width` | 2.6 m | 球门宽 |
| `circle_radius` | 1.5 m | 中圈半径 |
| `penalty_area_length` | 3.0 m | 大禁区（罚球区）进深 |
| `penalty_area_width` | 6.0 m | 大禁区宽 |
| `goal_area_length` | 1.0 m | 小禁区（球门区）进深 |
| `goal_area_width` | 4.0 m | 小禁区宽 |
| `penalty_dist` | 2.1 m | 罚球点距门线 |

> ③ **给摔倒的人加 `FALLEN_COST`（10 米）惩罚**——他物理上确实离球最近，但爬起来要好几秒，让他去追等于放弃这次拼抢，加一个大惩罚就等于说"除非别人远得离谱，否则别指望他"。这种"用代价函数代替硬规则"的写法非常好扩展。

> 己方球门在 `x = -7.0`（因为 length/2 = 7.0），对方球门在 `x = +7.0`。中圈半径 1.5m，意味着开球点附近 1.5m 内是对方开球时不能进入的区域。坐标是你做决策的尺子。
