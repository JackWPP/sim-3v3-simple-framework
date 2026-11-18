# 了解Player类

策略可以很复杂，但最终只会表现为三个机器人的动作。`Player` 类的职责就是转换意图为动作。你可以把它理解成机器人的**遥控器**。框架把三个机器人的遥控器造好塞给你，你按哪个键、什么时候按，就决定了球队踢得像不像样。

🎯 **学习目标**

- 理解 `Player` 的定位与生命周期；
- 掌握状态 `property` 与活性自理机制；
- 了解高层动作 `attack` / `guard` / `support` 的内部逻辑；
- 掌握编写自定义动作的规范方式。

---

## 单元1：Player是每个机器人的遥控器

`src/player.py` 里的 `Player` 是机器人的抽象，包含大量控制方法。

- **谁创造了 Player？** 框架在启动时（准确说是 `SoccerRuntime` 初始化阶段，runtime.py）会**为你自动创建 3 个 `Player` 实例**，每个对应一个机器人，id 分别是 1、2、3。你不需要、也不应该自己实例化 Player——它是平台按 `agent.toml` 里配置的机器人数量批量造好的。
- **如何使用 Player？** 框架把这三个 `Player` 打包成 `players` 列表，作为 `play(context, players, store)` 的第二个参数传给你（runtime.py）。之后你在 `_act_*` 里拿到某个 `Player`，调用它的方法，就是在给对应的那个机器人下指令。

<callout emoji="💡">
你不直接操作机器人硬件，而是使用遥控器 `Player`，`Player` 内部把战术意图翻译成 SDK 能懂的指令并下发。
</callout>

**Player 的生命周期**

`Player` 是机器人的控制器。你的策略决定每一帧按"攻击键"（`attack()`）还是"防守键"（`guard()`），决定机器人怎么动。

---

## 单元2：了解状态 `property` 与活性自理

在发任何指令前，了解机器人当前的状态十分必要。这就像开车前先看仪表盘：

| Player的property | 含义 | 用法 |
|-|-|-|
| `pose` | 当前位姿 `Pose2D`，看不见为 `None` | 走位/踢球的前提 |
| `mode` | 当前模式 | 非 walk 不能移动 |
| `is_fallen` | 是否摔倒 | 摔倒要先 `get_up()` |
| `is_penalized` | 是否被罚下 | 罚下只能起身/切模式 |
| `is_kicking` | 是否处于踢球中 | 用于可视化与迟滞 |

机器人是有重量、会摔跤、要守规则的真实机器。`is_fallen` 和 `is_penalized`两个属性说明机器人是否具备执行命令的条件。

比如 1 号球员抢球时被撞倒。这一帧中，你的代码算出1号离球最近，于是命令 `attacker.attack()`。`attack()` 内部会调 `walk_to()`，`walk_to()` 会调 `set_velocity()`。但机器人此刻处于摔倒/恢复模式，`mode` 不是 `"walk"`，速度指令被底层静默丢弃，没有任何报错。于是你在日志里看到机器人接到指令却一动不动。如果机器人刚好在起身动作的中途收到速度指令，两套动作打架，可能出现抽搐、原地打转这类诡异行为。

最佳实践是在每帧开始，调用所有球员的 `ensure_ready()` 方法，把本帧能动的人筛出来，只分派这些人战术。项目里的 `play()` 就是这么写的。摔倒的先 `get_up()`、非 `walk` 模式的先切模式，被罚下的直接 `stop()` 并跳过分派。

```Python
# src/player.py
def ensure_ready(self) -> bool:
    """活性自理：摔倒→起身，非 walk→切模式（都异步、不产生移动）。

    返回本帧是否可执行动作（True=已就绪）。
    """
    if self.is_fallen:
        self.get_up()
        return False
    if self.mode != "walk":
        self.request_mode("walk")
        return False
    return True
```

这就是机器人的活性自理。把自我维护的逻辑收进一个方法里，策略层不必到处写恢复逻辑。

为什么它返回 `False` 而不是等到恢复完成？因为 `get_up()` 和 `request_mode()` 都是异步的——发出去后要几十上百毫秒才生效，函数不能阻塞（整个循环是 30Hz，卡一帧全队都停摆）。所以它的语义是："我已经在处理了，但这一帧你别指望他动。"策略层拿到 `False` 就把这人排除出本帧分派，等下一帧再问一次，是最省事也最稳的写法。

---

## 单元3：Player类的高层动作

策略层部署战术动作，具体执行由 `Player` 内部决定（`player.py`）。

| 高层动作 | 行为 |
|-|-|
| `attack(target)` | 追球射门 |
| `guard()` | 守门，站小禁区中央待命 |
| `support()` | 站"球→己方门"连线上的补防点 |
| `take_kickoff()` | 我方开球：绕到球后、就位后踢 |
| `walk_to(target, ...)` | 走到目标点（带避障） |
| `face_to(theta)` | 原地转向到目标朝向 |
| `move_to_position(target)` | 走到站位点并面向球 |

### `attack()` 详解

`attack()` 不是简单"看到球就踢"，而是用**迟滞（hysteresis）**判断何时进入/退出踢球状态，避免边界抖动：

这张状态图描述了 `attack()` 中的状态机，有 `追球` 和 `踢球` 两种状态。踢球状态为进出设计了两个门槛，从 `追球` 变成 `踢球`要靠得比较近（2.0m），但已经在 `踢球` 状态时，要距离球更远（2.5m）才退出踢球状态。中间那 0.5m 就是缓冲带。只要机器人在 2.0\~2.5m 之间晃动，状态保持不变。

```Python
# src/player.py（节选）
d = dist(self.pose.x, ..., ball.x, ball.y)
self._kicking = d <= (KICK_EXIT_M if self._kicking else KICK_ENTER_M)
if self._kicking:
    self.kick(...)          # 进入踢球 → 踢
else:
    self.walk_to(_behind_ball(...))   # 否则绕到球后方
```

我们关注中间计算 `self._kicking` 的代码：已经在踢球（`self._kicking` 为真）就用宽松的 `KICK_EXIT_M`，还没踢球就用严格的 `KICK_ENTER_M`。

另一个值得学的细节在 `else` 分支。机器人不是走向球本身，而是走向球后方、球与球门连线的延长线上那个点 `_behind_ball(...)`。因为走到那儿时，机器人面向球就对准了球门方向，抬脚就能射。这就是用走位顺便完成瞄准的小心机。

<blockquote><p><b>为什么要"迟滞"（hysteresis）？</b></p><p><code>KICK_ENTER_M=2.0</code>、<code>KICK_EXIT_M=2.5</code>（<code>param.py</code>）。进入踢球的门槛（2.0m）比退出门槛（2.5m）<b>更小</b>，这叫迟滞。如果没有它，机器人在 2.0m 边界附近容易抽搐。迟滞是控制系统中消除边界抖动的经典技巧。<cite doc-id="QhaYwC8SniGAiukUQmxcQ9uZnkc" file-type="wiki" title="使用store设计跨帧策略" type="doc"></cite>会用 <code>store</code> 实现更通用的迟滞。</p></blockquote>

### `guard()` 详解

**`guard()`** 让球员走到**小禁区中央**站定，并把脸转向球，随时准备扑救或解围。

站位点使用 `own_goal_area_center(ctx)` 计算己方小禁区中心。位置的选择很有讲究，站在门线上会让对手有太多射门角度，站太靠前又容易被打身后。朝向上，参数 `GUARD_FACE_BALL`（`param.py`）决定要不要一直面向球。

```Python
# src/player.py（guard 节选）
home = own_goal_area_center(self.context) if self.context is not None else None
if home is None or self.pose is None:
    self.action = "guard:stop"
    self.stop()
    return

ball = self.context.ball if self.context is not None else None
face = 0.0
if GUARD_FACE_BALL and ball is not None:
    face = angle_to(self.pose.x, self.pose.y, ball.x, ball.y)

self.walk_to(home, face=face, avoid_ball=True, avoid_robots=True)
```

这段代码分三步：先兜底、再算朝向、最后一步走位。注意：

- `guard()` 是"站桩型"动作，它不会主动出击。如果你想要"对手逼近时守门员上前封堵"，需要自己在 `_act_normal` 里判断威胁、改调 `walk_to`。
- 用于判断是否到达的 `ARRIVE_DIST` 不要太小（默认 0.15m），否则容易导致机器人在目标点附近反复微调。
- `walk_to` 一定要打开 `avoid_ball=True`。守门员回位的路上容易把球碰入自家球门，宁可绕远也要躲开球。

### `support()` 详解

`support()` 让球员扮演第二道防线。站到球与己方球门中心的连线上，距球 `SUPPORT_DIST_M`（默认 3.0m）的位置，并面向球。它既是防守的补位点，也是丢球后第一时间反抢的接应点。

从球出发，沿"球 → 己方门中心"的单位方向走 3 米，就是站位点。这条连线是对手最短的进攻路线，卡在这条线上等于用身体挡住射门的必经之路。算出来的点还会被夹进场地内（不越过己方底线、不出边线 0.3m），避免球员走到场外。

```Python
# src/player.py（support 节选）
ball = self.context.ball
gx, gy = own_goal(ctx)
bx, by = (ball.x, ball.y)
dx, dy = gx - bx, gy - by
d = math.hypot(dx, dy)
ux, uy = (-1.0, 0.0) if d < 1e-6 else (dx / d, dy / d)
along = min(SUPPORT_DIST_M, d)          # 别越过球门
tx, ty = bx + ux * along, by + uy * along

half_l = ctx.field.length / 2.0
half_w = ctx.field.width / 2.0 - 0.3
tx = clamp(tx, -half_l + 0.3, half_l)   # 夹进场内
ty = clamp(ty, -half_w, half_w)
self.move_to_position((tx, ty))
```

`support()` 完全跟着球走，球在哪它就在"球到门"的线上。所以球快速横向移动时，`support` 球员会跑得很辛苦。如果移动成为战术瓶颈，可以考虑用 `store` 做迟滞，或者干脆改成区域防守。

---

## 单元4：Player的底层接口

底层接口直接对接 SDK，你通常不需要调，而是调用封装后的高层动作（`player.py`）。理解它们有助于你写自己的高层动作，或在调试时知道到底发了什么指令给机器人。

```Python
# src/player.py
def set_velocity(self, vx, vy, vyaw) -> None:
    self._backend.set_velocity(vx, vy, vyaw)   # 场地坐标系下的速度指令
```

这个函数很薄，把速度原样转交给 `_backend`。但这层薄封装是策略层通往硬件的唯一接口。所有动作最终都收敛到这一个出口，意味着你想加日志、加限速、加安全检查，只需要改这一处。`vx` 是前进速度、`vy` 是横移速度、`vyaw` 是转向角速度，三者同时下发，机器人就能一边走一边转。

| 接口 | 作用 | 注意 |
|-|-|-|
| `set_velocity(vx, vy, vyaw)` | 设定 x/y 线速度 + 转向角速度 | 真正让机器人动起来的唯一入口 |
| `stop()` | 速度清零 + 取消踢球 | 紧急停车用 |
| `kick(dir, power)` | 踢球（场地→体坐标自动转换） | `dir=None` 时自动调 `plan_kick()` |
| `release_kick()` | 清除踢球迟滞标志 | `walk_to` 开头会自动调用 |
| `ensure_ready()` | 摔倒→起身；非 walk→切模式 | 返回 `True` 才代表"本帧可动" |

`kick()` 接收的是场地坐标系下的方向（`player.py`），但机器人只懂"球在我身体的哪个方位"。于是 `kick()` 内部用当前 `pose.theta` 做旋转，把场地方向翻译成"体坐标方向"再下发。你只管说"往对方门踢"，转身的事 `Player` 替你算好了。

```Python
# src/player.py（核心几行）
dx = ball.x - pose.x; dy = ball.y - pose.y
ball_x_body = dx * cos_t + dy * sin_t     # 旋转到体坐标
direction_body = normalize_angle(kick_direction - pose.theta)
self._backend.kick(direction_body, power_clamped, ball_x_body, ball_y_body)
```

这四行做的是一次坐标系旋转：把"世界怎么看"翻译成"机器人自己怎么看"。前两行用旋转矩阵把"球相对我的位移"从场地坐标转到体坐标（`cos_t`/`sin_t` 就是 `cos(pose.theta)`/`sin(pose.theta)`），机器人就知道"球在我左前方 0.3 米"；第三行同理把踢球方向做角度差，还用 `normalize_angle` 把结果规范到 `[-π, π]`——不做归一化的话，359° 和 -1° 会被当成天差地别的两个方向，机器人会绕个大圈去转身。最后一行把力度 `power_clamped` 夹进 `KICK_POWER_MIN~MAX`）一起下发，因为超出接口支持范围的大力抽射，真机会直接把自己踢摔倒。

绝大多数情况你只用高层动作（`attack`/`guard`/`support`/`walk_to`），它们已经帮你处理了坐标转换、避障、迟滞。只有当你要做非常定制的行为（比如"以特定力度、特定角度直接踢一脚"）时，才需要直接用 `kick()` 或 `set_velocity()`。

---

## 单元5：自定义Player行为

`Player` 提供的七个高层动作覆盖了大部分常规场景。如果你遇到以下三种情况，就该考虑自定义了：

1. **现成动作表达不了你的战术意图**。比如你想让一名球员堵住对方的传球路线。在目前的示例策略中找不到对应动词，就自己造一个。
2. **把多个底层动作组合成一个稳定的行为**。比如"走过去 + 到位后面向球门 + 到位后原地待命"，如果每次都在 `_act_normal` 里写三四行，代码会越堆越乱；封装成一个函数，调用处就只剩一行，可读性和复用性都上一个台阶。
3. **现成动作上加判断或修正**。比如 `support()` 但绝不越过中线。

相反，**这几种情况不要自定义**：

1. 只是想调整距离/力度/门槛 → 去改 `param.py`（第 7 篇）；
2. 只是想换个站位点 → 直接 `walk_to(新点)` 就行，没必要包函数；
3. 想改的是"什么时候用哪个动作" → 那是状态机和角色分派的事（第 3 篇），不是动作本身的事。

---

## 🧪 章节练习

1. **写一个"盯人"动作**：让指定球员始终跟在某个对手与我方球门之间，距离对手约 1.0 米，并面向对手。

   - 提示：从 `context.opponents.get(opponent_id)` 取对手位姿；用 `own_goal(context)` 算出"对手 → 我方门"的单位方向向量，沿它走 1.0 米得到站位点；最后 `walk_to(站位点)` + `face_to(angle_to(自己, 对手))`。
   - 进阶：把跟随距离做成参数 `dist_m=1.0`，并加一个"只在对手进入我方半场时才盯人"的条件。
2. **写一个"回防到禁区前沿"动作** ：让球员退回己方大禁区前沿（`x = -4`），横向对齐球的 y 坐标（但夹在禁区宽度内），并面向球。

   - 提示：目标点 `(-4.0, clamp(ball.y, -3.0, 3.0))`；用 `move_to_position` 可以一步搞定"走过去 + 面向球"。
   - 进阶：加一个"已经在位就别动"的判断，避免机器人在目标点附近反复微调。
3. **对比实验**：把 `_act_normal` 里的 `support()` 换成你写的 `fall_back_to_box()`，跑一局仿真，观察丢球后的回防速度有没有变化。想一想：什么局面下"跟着球站位"（support）更好，什么局面下"固守禁区前沿"更好？

---

## 📖 扩展阅读

- **反应式控制（Reactive Control）**：[https://en.wikipedia.org/wiki/Behavior-based_robotics](https://en.wikipedia.org/wiki/Behavior-based_robotics)
- **迟滞比较器（Hysteresis）**：[https://en.wikipedia.org/wiki/Hysteresis](https://en.wikipedia.org/wiki/Hysteresis)
- **坐标系与变换**：[http://wiki.ros.org/tf](http://wiki.ros.org/tf)

---

## 📌 要点总结

- **`Player` 是单个机器人的遥控器**，框架启动时造好 3 个，通过 `players` 列表交给你在 `play()` 里使用；
- **高层动作**：`attack`/`guard`/`support`/`walk_to`/`face_to`/`take_kickoff`；
- **底层接口**：`set_velocity`/`kick`/`ensure_ready`/`release_kick`，直接对接 SDK；
- `attack` 用 `KICK_ENTER_M < KICK_EXIT_M` 的设计消除边界抽搐；
- 需要 `Player` 没现成提供的行为时，用高层原语拼一个自己的函数即可。