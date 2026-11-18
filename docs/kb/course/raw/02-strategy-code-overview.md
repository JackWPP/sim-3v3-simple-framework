# 策略代码概述

上个模块我们在本地使用示例策略开始了一场比赛，这一模块我们来深入理解示例策略。我们将了解示例策略代码分成哪三层、每层归谁管、框架在高频做怎样的计算，战术决策是怎么一路变成机器人动作的。如果理解了数据从哪来、指令发到哪，优化策略会更得心应手。

🎯 **学习目标**

- 看懂项目的三层结构；
- 理解 30Hz 控制循环；
- 理解平台适配层 `framework/`。

---

## 单元1：项目地图

项目文件结构图：

```Plaintext
sim-3v3-simple-framework/
├── agent.toml              # 配置：Agent 元数据：名称、描述、入口类（平台读取）
├── build.toml              # 配置：构建依赖与命令（平台构建时用）
├── src/
│   ├── main.py             # 策略主战场：SoccerSimAgent + play() + Phase 状态机 + 三角色分派
│   ├── player.py           # 控制手柄：Player 类：对"一个机器人"的全部动作（走/踢/守）
│   ├── param.py            # 调参面板：所有可调参数集中在这里，改一处全局生效
│   ├── framework/          # 平台适配层：把"通用足球策略"翻译成"机器人指令"（通常不改）
│   │   ├── runtime.py      # 30Hz 主循环、Context 构造、Player 生命周期管理
│   │   ├── agent.py        # 框架装配 play/init_store 槽、激活/关闭钩子、日志桥接
│   │   ├── types.py        # 数据契约：Context / Pose2D / BallState ...（无平台依赖、可单测）
│   │   ├── config.py       # 每场身份：team_id、control_hz、新鲜度阈值（读环境变量）
│   │   ├── ros_source.py   # ROS 数据源（真机/容器专属，延迟导入避免污染开发机）
│   │   ├── robot_backend.py# SDK 包装：把 set_velocity/kick 翻译成真机指令
│   │   ├── game_codec.py   # 裁判机数据编解码
│   │   ├── debugdraw.py    # 把可视化标记（点/线/箭头/文字）渲染到仿真环境
│   │   └── log_publisher.py
│   └── utils/              # 通用工具：纯函数、无状态、可单测，谁写策略都能用
│       ├── geom.py         # dist / angle_to / 坐标转换 / opponent_goal / own_goal
│       ├── obstacles.py    # 障碍建模与收集（球/对手/队友/球门）
│       └── path_planner.py # A* 全局路径规划
└── docs/                   # 文档
```

选手可以把比赛策略想象成一家不断出餐的餐厅：

- **`framework/`** 是基础设施，也就是厨房的水电网，没人天天改它，但缺了它后厨转不起来。
- **`utils/`** 是切菜、称重这些通用技能，谁做菜都能调用。
- **`player.py`** 是"厨师的操作手册"，指导厨师怎么切、怎么翻锅（对应一个机器人怎么走、怎么踢）。
- **`main.py`** 是"主厨的管理手册"，决定谁去切、谁去翻、谁去摆盘（对应每帧决定谁进攻、谁防守、谁支援）。

刚入门的选手，可以从修改`main.py`和`player.py`开始。**`framework/`** 和**`utils/`** 已经做了充分封装，建议深入理解比赛和策略框架的选手再修改。 

> 此步骤可借助AI Assistant完成，参考提示词：请先帮我逐行讲解 src/main.py 中 play() 和 src/player.py 中 Player 类的作用，然后告诉我从哪个函数入手修改策略最合适。

**示例策略的三层结构：**

策略越往上越贴近战术，越往下越通用。策略代码集中在上面两层，底层负责把意图变成行动。策略的架构分工明确，每层向下依赖，单向依赖保证 `player.py` 永远不会去调用 `main.py` 里的战术函数，`utils/` 也不知道"进攻"是什么意思。你可以大胆重写上层战术，而不用担心破坏下层。

---

## 单元2：30Hz 控制循环的一帧里发生了什么

比赛开始后，Agent 开启 30Hz 的主循环。每秒约 30 次，反复做同一件事。频率由 `SoccerConfig.control_hz`控制，见 `src/framework/config.py`。

机器人足球比赛节奏快，机器人需要高频响应指令。太慢（比如 5Hz），机器人会显得迟钝、追不上球；太快（比如 100Hz），单次决策时间不够、还浪费算力。30Hz 是实践中响应速度和计算量的平衡点。

在一次帧循环中：

每次循环中，框架构造 `Context` → 调用 `play(context, players, store)` → `play()` 使用 `Player` 方法 → 经 `RobotBackend` 下发 SDK 指令。具体来说，会经过以下步骤：

1. **ROS 原始数据到位**（`ros_source.py`）。仿真器把这一瞬间的原始信号推过来，包括机器人的位姿、球的位置、比赛的阶段等；
2. **`_build_context` 打包快照**（`runtime.py`）。框架把零散信号整理成一个结构化的 `Context` 对象，帮你拿到当下可信的事实；
3. **调用 `play()`开始决策**（`main.py`）。框架把 `Context`、三个 `Player` 遥控器、`store` 记忆容器一起递给 `play()`。`play()` 开始战术思考；
4. **调用遥控器上的战术动作**（`main.py` → `player.py`）。`play()` 经过计算表达战术意图，调用 `Player` 的高层动作，比如让1号机器人进攻，执行 `attack()`；
5. **`Player` 把意图翻译成运动指令**（`player.py`）。`attack()` 内部开始算账：球在我前方偏左一点 → 需要多大的前进速度和转向角速度？路上有没有对手挡着？ → 要不要绕一下？离球够近了吗 → 够近就不再走，改成 `kick`，力度按射门参数取，方向瞄准对方球门中心。最终一切都收敛到两个底层接口：`set_velocity` 或 `kick`；
6. **`RobotBackend` 下发指令给机器人**（`robot_backend.py`）。这一跳把 `set_velocity/kick` 翻译成平台 SDK 认识的底层报文，真正送到机器人身上。于是1号机器人射门，球飞向球门；
7. **下一帧重新开始**。1/30 秒后，球的位置变了，`Context` 是全新的，`play()` 再次被唤醒，开始运转。

`play()` 被 `runtime`以固定频率调用，就像被按了快门的相机——每 1/30 秒拍一张世界的照片（`Context`），并立刻决定这一下怎么动，然后等下一按。对于大多数策略思路，选手不用考虑循环本身，只要确定"这一帧怎么决策"。

`src/framework/runtime.py` 中关键代码位置：

- 循环主体：`SoccerRuntime._loop()` 与 `_tick()`；
- 每帧构造感知数据：`_build_context()`；
- 调用决策逻辑：`self._agent.play()`。

---

## 单元3：策略入口play() 方法

`src/main.py` 是策略文件的入口，核心是 `SoccerSimAgent` 类，它继承自框架提供的基类。你通常只需要关心 `play` 方法。**`play(context, players, store)` 是每帧触发一次的决策主函数**。做出决策需要三样东西：

- `context`：本帧的世界动态（球和球员的位置、裁判状态…），详见<cite doc-id="MfXNwA1wziqAScke8RzckI9pnwh" file-type="wiki" title="使用Context判断比赛动态" type="doc"></cite>；
- `players`：机器人运动员 `Player` 实例，你调用它们的方法来指挥机器人，详见<cite doc-id="ZXdWwcXo2i555Dk8lIRcB2brnph" file-type="wiki" title="了解Player类" type="doc"></cite>；
- `store`：记忆容器，可以跨帧存储策略信息，用来设计跨帧策略，详见<cite doc-id="QhaYwC8SniGAiukUQmxcQ9uZnkc" file-type="wiki" title="使用store设计跨帧策略" type="doc"></cite>。

![图片展示了足球机器人策略 飞书机器人足球 2.0 的 `play()` 方法流程。流程分为四步：1. 读取 `context`，包括 `game`、`ball`、`teammates`、`echa](https://feishu.cn/file/YtYLbz453oFS4Zx4Ub5cBjTqnle)

`play()` 的核心逻辑如下：

```Python
# src/main.py（骨架，已精简注释）
def play(self, context, players, store):
    # 1) 先判断当前比赛处于什么阶段，记录阶段边沿
    phase = get_phase(context)
    store.prev_phase = store.cur_phase
    store.cur_phase = phase

    # 2) 活性自理：摔倒的起身、被罚下的别动、位置未知的别分派
    active = []
    for p in players:
        p.ensure_ready()
        if p.is_penalized or p.pose is None:
            continue
        active.append(p)

    # 3) 按阶段分派到对应的处理函数
    if phase == Phase.NORMAL:
        _act_normal(context, active, store)
    elif phase == Phase.OUR_KICKOFF:
        _act_our_kickoff(context, active, store)
    elif phase == Phase.OPP_KICKOFF:
        _act_opp_kickoff(context, active, store)
    elif phase == Phase.OUR_SET_PLAY:
        _act_our_set_play(context, active, store)
    elif phase == Phase.OPP_SET_PLAY:
        _act_opp_set_play(context, active, store)
    elif phase == Phase.READY:
        _act_ready(context, active, store)
    else:   # STOPPED
        for p in active:
            p.stop()
```

你可以把 `play()` 理解成"每帧开一次的战术会议"。这场会议只开 1/30 秒：

- 第一步，算 `Phase`，看清楚现在是什么局面。通过裁判机消息，确认"现在是正常拼抢"、"现在是对方任意球"还是"现在还没开赛"。同时顺手记下"上一帧是什么局面"，方便识别比赛状态是否切换。
- 第二步，筛出 `active`，寻找可用球员。机器人不是永远待命，摔倒的要先调 `ensure_ready()` 让它爬起来、被罚下的根本不许动、还有的连自己在哪都不知道。它们虽然在 `players` 列表里，却不能被安排任务。滤掉它们后剩下的，才是本帧真正能干活的球员，也就是 `active` 列表。
- 第三步，按局面把 `active` 交给对应的行动计划。这里不会讨论细节，只做转交。正常拼抢就交给 `_act_normal`，我方定位球就交给 `_act_our_set_play`，比赛暂停大家就原地站好。
- 最终，各个 `_act_*` 指挥具体球员跑位、抢球、射门。

本质上，所有优化要么是在改写对 `Phase`的理解，要么是在改写特定 `Phase`分支中 `_act_*` 的逻辑。

> 此步骤可借助AI Assistant完成，参考提示词：我想让球队在某一个比赛阶段（例如我方定位球）采用新的打法，请帮我改写对应的 \_act\_\* 函数，并说明改动对 Phase 理解的影响。

---

## 单元4：平台适配层 `framework/`

`framework/` 是策略框架的基础支撑层，负责向上提供统一的数据与生命周期管理，向下对接 Booster 平台的机器人底盘与通信 SDK，把上层的**战术意图**翻译为实时的**机器人指令**。各模块职责与核心类/方法如下：

| 模块 | 职责 | 重点类 / 方法 |
|-|-|-|
| `runtime.py` | 30Hz 主循环的发动机。它每秒约 30 次：从数据源取感知 → 调 `_build_context` 构造 `Context` → 调你的 `play()` → 帧末 `debugdraw.flush()` 把可视化下发。还负责 `Player` 的生命周期（创建、激活、关闭）。 | `SoccerRuntime._loop()`（循环主体）、`_tick()`（单帧）、`_build_context()`（构造 Context + 新鲜度过滤） |
| `agent.py` | 框架的"装配工 + 钩子"。它把你的 `play` / `init_store` 槽接进生命周期，并提供 `on_agent_activated` / `on_agent_close` 两个回调，还做日志桥接。 | `SoccerSimAgent`（你的 `main.py` 里 `SoccerSimAgent` 的基类）、`on_agent_activated()` / `on_agent_close()` |
| `types.py` | 数据类型的统一定义处。所有"你每帧看到的"和"你下命令用的"数据结构都在这里定义。这是你了解 `Context` 唯一需要翻的文件。 | `Context`、`Pose2D`、`BallState`、`RobotState`、`GameControlState`、`Phase`、`FieldDimensions` |
| `config.py` | 每场比赛的"身份信息"来源：队伍编号、控制频率、新鲜度阈值等，全部从环境变量读取。想让机器人反应更快/更慢，在这里改 `control_hz`。 | `SoccerConfig`（`control_hz` / `team_id` / `freshness_threshold`） |
| `ros_source.py` | ROS 数据源。从仿真器或真机订阅原始感知话题（机器人位姿、球、裁判机），提供给 `runtime` 打包成 `Context`。 | `RosSource`（订阅感知话题、提供原始位姿/球/裁判机） |
| `robot_backend.py` | SDK 包装层。把 `Player` 算出的 `set_velocity` / `kick` 翻译成平台 SDK 能懂的底层指令，下发给机器人。 | `RobotBackend.set_velocity()` / `.kick()` |
| `game_codec.py` | 裁判机数据的编解码器。把平台发来的裁判信号解析成 `GameControlState`（比分、阶段、定位球类型等）。 | `GameCodec`（解析 `GameControlState`） |
| `debugdraw.py` | 可视化工具。把你想"画在场上"的标记渲染到仿真环境。 | `DebugDraw.point()` / `.line()` / `.arrow()` / `.text()` |
| `log_publisher.py` | 日志发布。把运行日志推到平台日志面板。 | `LogPublisher` |

当你遇到问题时，可按上表里的 `重点类/方法`顺藤摸瓜。比如，看不到球就查 `_build_context` 和 `RosSource`；踢球没反应就查 `RobotBackend.kick`。

建议选手读源码时，优先吃透 `main.py` 和 `player.py`。`framework/` 中的组件知道作用即可，一般不需要改。如果要部署真机或修改数据源，再来深挖 `robot_backend.py` 和 `ros_source.py`。

---

## 📖 扩展阅读

- [**RoboCup 标准平台组规则**](https://ssl.robocup.org/rules)

---

## 📌 要点总结

- 策略是三层结构，单向向下依赖；
- 控制循环高频刷新，每次循环中构造 `Context` ，调用 `play()` ，用 `RobotBackend`下发指令；
- `framework/` 通常不改。