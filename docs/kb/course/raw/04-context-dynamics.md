# 使用Context判断比赛动态

状态机的每一次判断，都要有"看得见的世界"作依据。这个世界就是 `Context`，它是框架每帧递到你手里的只读快照。球在哪、队友在哪、对手在哪、裁判机怎么说，全在里面。读懂它，你才能把"球在我方半场就回防"这样的人话，翻译成机器人真正听得懂的判断。

🎯 **学习目标**

- 读懂只读世界快照 `Context`
- 了解裁判机 GameControlState 的关键字段
- 学会把战术拆成"读字段→算数值→调动作"

---

## 单元1：策略的眼睛Context

如果说`play()`是大脑，`Context`就是\*\*眼睛。`Context` 只读快照由框架每帧构造，作为参数传入 `play()`，在 `src/framework/types.py` 定义：

```Python
# src/framework/types.py
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

每帧生成的 `Context` 中包含全部的世界信息。信息被打包成不可变的数据类：时间（`now`/`dt`）、身份（`team_id`）、静态场地（`field`）、动态观测（`game`/`ball`/`teammates`/`opponents`）各占一格，互不干扰。你写 `play()` 时，要格外关注这唯一的外部信息参数。

| 字段 | 含义 | 你能拿它做什么 |
|-|-|-|
| `now` / `dt` | 当前时间 / 距上一帧的时间差（秒） | 算速度、做"每 N 秒触发一次"的节奏控制 |
| `team_id` | 我方队伍编号（1 或 2） | 区分主客队视角、读取对应队伍比分 |
| `field` | 场地尺寸（长度、宽度、球门宽…） | 所有"出界/危险区"判断的物理边界 |
| `game` | 裁判机状态（比分、阶段、定位球类型…） | 决定 Phase、读比分、判断谁主罚 |
| `ball` | 球的位置/置信度 | 追球、射门、判断归属的核心数据（可能 `None`） |
| `teammates` | 我方球员位姿，键是球员 id（1..3） | 分派角色、算谁离球近 |
| `opponents` | 对方球员位姿，键是球员 id | 避障、判断威胁、对手建模 |

<blockquote><p>你永远可以信任 <code>Context</code></p><p><code>Context</code> 标注了 <code>@dataclass(frozen=True)</code>（types.py），意味着它是不可变的。你不能在 <code>play()</code> 里修改它（<code>ctx.ball.x = 1</code> 会直接抛错）。因为感知数据是事实，策略只能读取事实、再决定动作，而不能篡改事实。</p><p>所有战术记忆应该写进 <code>store</code>（参考<cite doc-id="QhaYwC8SniGAiukUQmxcQ9uZnkc" file-type="wiki" title="使用store设计跨帧策略" type="doc"></cite>）。 </p></blockquote>

---

## 单元2：关键数据类型速查

解析 `Context` 前，我们先来了解它使用的几个数据结构

机器人位置是 `Pose2D`。

```Python
@dataclass(frozen=True)
class Pose2D:
    x: float = 0.0
    y: float = 0.0
    theta: float = 0.0     # 朝向角（弧度），0 表示朝 +x
```

这是策略中最基础的位置信息。平面上点坐标加朝向，共三个浮点数。`x`/`y` 的单位是米，`theta` 是弧度。

**BallState**（`types.py`）。

```Python
@dataclass(frozen=True)
class BallState:
    x: float = 0.0
    y: float = 0.0
    last_seen_at: float = 0.0     # 上次观测到球的时间
    confidence: float = 1.0
```

球的位置只有 `x`/`y`（球不需要朝向），额外两个元信息字段。`last_seen_at` 记录获得当前观测的时间，`confidence` 表示视觉有多确信。这两个字段主要用于视觉辅助定位。

**RobotState**（`types.py`）。

```Python
@dataclass(frozen=True)
class RobotState:
    player_id: int
    pose: Pose2D | None = None     # 位姿未知时为 None
    last_seen_at: float = 0.0
```

这里把"这个机器人是谁"（`player_id`）和"他在哪"（`pose`）拆开了，而且 `pose` 允许为 `None`。

**GameControlState**（`types.py`）对应 `context.game`，装着"比赛现在处于什么规则状态"，它是状态机判定 Phase 的唯一依据。

```Python
# src/framework/types.py（节选关键字段）
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

代码把裁判机（`GameController`）广播的整个数据包映射成了 Python 数据类。

---

## 单元3：理解坐标系

写策略时，你可以只站在自己队伍的视角思考，并以进攻视角建立坐标系。对于双方球队，"对方球门"永远在 `+x` 方向，"自家球门"永远在 `-x` 方向。仿真环境执行你提交的策略时，会自动转换坐标系，不依赖绝对坐标系。这保证了无论你在场上向左还是向右进攻，策略代码中的坐标逻辑相对稳定。你只需要写一套"往 +x 方向进攻"的逻辑，平台自动帮你处理。

坐标约定：

- +x 朝对方球门，-x 朝己方球门，场地中心为 `(0,0)`。
- 朝向角 `theta`：`theta=0` 表示机器人面朝 `+x`（即面朝对方门）。
- `opponent_goal(ctx)` 返回 `(field.length/2 + 深度, 0)`——对方球门中心（utils/geom.py）。
- `own_goal(ctx)` 返回 `(-field.length/2, 0)`——己方球门中心（utils/geom.py）。

  
本项目坐标系设计与 ROS 常用的 `map`/`odom` 帧思路一致（原点固定、x 轴朝前）。策略逻辑与机器人位姿解耦，让一套代码处处可用，也方便和队友分工：你改进攻、他改防守，都用同一套坐标语言。

你可以使用下方的工具理解坐标系，全屏体验更佳：

<figure view-type="Preview"><source name="战术板-策略调试工具.html" mime="text/html" size="17783" token="KhMkbvO6IoETkYxpiA7cxXvGntg"/></figure>

---

## 单元4：场地尺寸

`ADULT_FIELD_DIMENSIONS`（`types.py`）定义了场地尺寸：

| 参数 | 值 | 含义 |
|-|-|-|
| `length` | 14.0 m | 场地长（沿 x） |
| `width` | 9.0 m | 场地宽（沿 y） |
| `goal_width` | 2.6 m | 球门宽 |
| `circle_radius` | 1.5 m | 中圈半径 |
| `penalty_area_length` | 3.0 m | 大禁区（罚球区）进深 |
| `penalty_area_width` | 6.0 m | 大禁区宽 |
| `goal_area_length` | 1.0 m | 小禁区（球门区）进深 |
| `goal_area_width` | 4.0 m | 小禁区宽 |
| `penalty_dist` | 2.1 m | 罚球点距门线 |

很多"球出没出界""对方是否进入危险区"的判断，本质都是拿 `ball.x/ball.y` 和这些尺寸做比较。比如危险区的定义可能是 `ball.x < -penalty_area_length` 且 `|ball.y| < penalty_area_width/2`。把这些数字记在心里，你写判断时会快很多。

<callout emoji="💡">
己方球门在 `x = -7.0`（因为 length/2 = 7.0），对方球门在 `x = +7.0`。中圈半径 1.5m，意味着开球点附近 1.5m 内是对方开球时不能进入的区域。坐标是你做决策的尺子。
</callout>

## 单元5：解析Context示例

知道 `Context` 里有什么还不够，写策略需要把战术翻译成"读哪些字段、算什么、调哪个动作"。本单元给出一套**通用的解析方法**。

写策略时可以使用下面的表。想好战术意图后，在第二列中查找要从 `Context` 中读取的信息，并使用第三列中的判断逻辑。

| 战术意图 | 读哪些字段 | 怎么算（判据） |
|-|-|-|
| 球在我方半场就回收 | `context.ball.x` | `ball.x < 0` |
| 支援球员回撤保护 | `context.teammates` + 角色分派 | 挑本帧被派为 support 的那个 `Player` |
| 谁去追球（选 attacker） | `context.ball` + 各 `p.pose` | 到球距离最小者（摔倒者加惩罚） |
| 球进入我方危险区 | `ball.x/y` + `context.field` | `ball.x < -4.0` 且 `\|ball.y\| < 3.0` |
| 比分落后要压上 | `context.game.teams[].score` | 我方 score < 对方 score |
| 剩余时间不多 | `context.game.secs_remaining` | `< 60` |
| 现在是我方开球 | `game.secondary_time`、`kicking_team` | `secondary_time > 0` 且 `kicking_team == team_id` |
| 对方定位球要退开 | `game.set_play`、`kicking_team` | `set_play != NONE` 且 `kicking_team != team_id` |
| 对手压进我方禁区 | `context.opponents[].pose` | 统计 `pose.x < -4.0` 的对手数 |
| 球丢了看不见 | `context.ball` | `ball is None` |
| 机器人摔倒/被罚 | `p.is_fallen` / `p.is_penalized` | 布尔判断 |

**例子：算出"离球最近的我方球员"**

这是使用频率最高的解析，几乎每一帧都要回答"这球该谁去追"：

```Python
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

这段代码把"谁离球最近"这个模糊问题，变成一次**带惩罚项的最小值搜索**。三个关键点：

①**先判 `ball is None`**，因为球看不见时，宁可返回 `None` 让上层走保守分支；

②**跳过不可用的球员**，把动不了的人选成 `attacker` 会导致该帧无人进攻；

③**给摔倒的人加 `FALLEN_COST`（10 米）惩罚**——他物理上确实离球最近，但爬起来要好几秒，让他去追等于放弃这次拼抢，加一个大惩罚就等于说"除非别人远得离谱，否则别指望他"。这种"用代价函数代替硬规则"的写法非常好扩展：以后想让守门员优先留守，只要给他也加个惩罚项就行。

> 此步骤可借助AI Assistant完成，参考提示词：请帮我给 closest_player_to_ball 增加新的代价项，例如“守门员优先留守（加惩罚项）”“球在我方半场时优先选择更靠前的前锋追球”。

---

## 📖 扩展阅读

- **ROS `tf` 坐标变换文档**：[http://wiki.ros.org/tf](http://wiki.ros.org/tf)：理解坐标系在多机器人系统里的重要性。

---

## 📌 要点总结

- **Context 是策略的眼睛**，为 `play()` 提供只读世界快照；
- **核心数据类型**：`Pose2D`、`BallState`、`RobotState`、`GameControlState`；
- **坐标系约定**：+x 朝对方门、-x 朝己方门，原点 (0,0)，theta=0 面朝对方门；
- **场地尺寸**：length=14m、width=9m、球门宽 2.6m，出界/危险区判断都拿 `ball.x/y` 和这些数比较；
- **解析套路**：战术意图 → 读哪些字段并算出判据 → 调哪个动作。