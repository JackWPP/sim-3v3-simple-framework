# 02 策略代码概述
> 来源：https://booster.feishu.cn/wiki/SCi5wdAbZiSrsJki2QYceMMFnVh（原文约 7.8k 字）

## 一、核心要点

- 策略代码是**三层结构**，上层贴近战术、下层通用：`main.py`（主厨管理手册：每帧决定谁进攻/防守/支援）→ `player.py`（厨师操作手册：一个机器人怎么走、怎么踢）→ `framework/` + `utils/`（基础设施与通用技能）。
- **单向向下依赖**是硬约束：原文"`player.py` 永远不会去调用 `main.py` 里的战术函数，`utils/` 也不知道'进攻'是什么意思"→ 因此可以**大胆重写上层战术而不破坏下层**。
- 平台主循环是 **30 Hz**：`SoccerConfig.control_hz`（`src/framework/config.py`）控制，每秒约 30 次重复同一件事。
- 为什么是 30 Hz：**太慢（如 5 Hz）机器人迟钝、追不上球；太快（如 100 Hz）单次决策时间不够、还浪费算力**。30 Hz 是"响应速度与计算量的平衡点"（原文未给出实测数据，只给这一判断）。
- 一帧的完整链路（**7 步，原文逐条列出**）：
  1. **ROS 原始数据到位**（`ros_source.py`）：仿真器推送机器人位姿、球位置、比赛阶段等原始信号；
  2. **`_build_context` 打包快照**（`runtime.py`）：把零散信号整理成结构化 `Context`；
  3. **调用 `play()`**（`main.py`）：框架把 `Context`、三个 `Player` 遥控器、`store` 记忆容器一起递给 `play()`；
  4. **调用遥控器上的战术动作**（`main.py` → `player.py`）：如让 1 号机器人执行 `attack()`；
  5. **`Player` 把意图翻译成运动指令**（`player.py`）：球在前方偏左 → 算前进速度与转向角速度 → 判断是否有对手挡路、要不要绕 → 距离够近则改 `kick`，方向瞄准对方球门中心。**最终一切收敛到两个底层接口：`set_velocity` 或 `kick`**；
  6. **`RobotBackend` 下发指令**（`robot_backend.py`）：把 `set_velocity`/`kick` 翻译成平台 SDK 报文；
  7. **下一帧重新开始**：1/30 秒后 `Context` 全新，`play()` 再次被唤醒。
- 原文类比：`play()` 像"被按了快门的相机"——每 1/30 秒拍一张世界的照片（`Context`），立刻决定这一下怎么动，然后等下一按。**选手通常不用考虑循环本身，只确定"这一帧怎么决策"**。
- 决策需要三样东西：`context`（本帧世界动态）、`players`（`Player` 实例，调其方法指挥机器人）、`store`（跨帧记忆，用来做跨帧策略）。
- `play()` 的三步骨架：**算 Phase 并记录边沿 → 活性自理（摔倒起身/罚下不动/无位姿不分派）→ if/elif 分派到 `_act_*`**，`STOPPED` 分支全员 `stop()`。
- 原文的"优化公理"：**所有优化，要么是在改写对 `Phase` 的理解，要么是在改写特定 `Phase` 分支中 `_act_*` 的逻辑。**
- `framework/` 是平台适配层，**通常不改**；原文建议先吃透 `main.py` 和 `player.py`，`framework/` 的组件"知道作用即可"；只有部署真机或改数据源时才深挖 `robot_backend.py`、`ros_source.py`。
- `runtime.py` 关键位置：循环主体 `SoccerRuntime._loop()` 与 `_tick()`、每帧构造感知 `_build_context()`、调用决策 `self._agent.play()`；帧末 `debugdraw.flush()` 把可视化下发。
- `framework/` 排障入口（原文"顺藤摸瓜"）：**看不到球 → 查 `_build_context` 和 `RosSource`；踢球没反应 → 查 `RobotBackend.kick`**。

## 二、代码与公式

原文给出的 `play()` 骨架（`src/main.py`，原注释保留）：

```python
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

`player.py` 中 `attack()` 的"算账"过程（原文文字描述，落到代码即以下链路，属本项目实测对照）：

```python
# 意图 → 指令的唯一收敛点(两个底层接口)
self.set_velocity(vx, vy, vyaw)                      # 走位
self._backend.kick(direction_body, power, bx, by)    # 踢球(场地角→体坐标)
```

原文的 `framework/` 职责表（排障必查）：

| 模块 | 职责 | 重点类 / 方法 |
|---|---|---|
| `runtime.py` | 30 Hz 主循环发动机：取感知 → `_build_context` → 调 `play()` → 帧末 `debugdraw.flush()`；管 `Player` 生命周期 | `SoccerRuntime._loop()`、`_tick()`、`_build_context()` |
| `agent.py` | 装配工 + 钩子：把 `play`/`init_store` 接进生命周期，提供 `on_agent_activated`/`on_agent_close`，日志桥接 | `SoccerSimAgent`、`on_agent_activated()`、`on_agent_close()` |
| `types.py` | 数据契约：所有"每帧看到的"和"下命令用的"结构 | `Context`、`Pose2D`、`BallState`、`RobotState`、`GameControlState`、`Phase`、`FieldDimensions` |
| `config.py` | 每场身份：队伍编号、控制频率、新鲜度阈值，全部从环境变量读 | `SoccerConfig`（`control_hz`/`team_id`/`freshness_threshold`） |
| `ros_source.py` | ROS 数据源：订阅机器人位姿、球、裁判机 | `RosSource` |
| `robot_backend.py` | SDK 包装：`set_velocity`/`kick` → 底层报文 | `RobotBackend.set_velocity()`、`.kick()` |
| `game_codec.py` | 裁判机数据编解码 → `GameControlState`（比分、阶段、定位球类型） | `GameCodec` |
| `debugdraw.py` | 可视化：把点/线/箭头/文字渲染到仿真环境 | `DebugDraw.point()/.line()/.arrow()/.text()` |
| `log_publisher.py` | 日志推到平台日志面板 | `LogPublisher` |

## 三、易错点

- 【原文】**反向依赖**：在 `player.py` 里 `from .main import ...` 或在 `utils/` 里判断"进攻/防守"。原文把单向依赖列为架构保证，破坏它会让上层战术无法整体重写。
- 【原文】**越过 `Player` 直接发速度**：`Player` 的职责是把战术意图翻译为 `set_velocity`/`kick`；在 `_act_*` 里手搓速度等于绕开避障、踢球迟滞、模式切换等封装。
- 【原文】**在 `play()` 里关心循环**："对于大多数策略思路，选手不用考虑循环本身，只要确定'这一帧怎么决策'"——不要把 `while`、计时器、`sleep` 塞进策略。
- 【原文】**一上来就深挖 `framework/`**。原文明确"通常不改"，且平台构建校验认入口类直接基类（见 `src/framework/agent.py:1-10` 注释），动框架容易直接构建失败。
- 【原文骨架 vs 本项目现状】**原文骨架是精简版**：它只写 `if p.is_penalized or p.pose is None: continue`；当前 `src/main.py:147-159` 实际有 4 个分支（`penalized`→`stop()`、`not ready`→标 `fallen`/`switching_mode`、`pose is None`→`no_pose`+`stop()`、否则入 `active`），动作标签也更细。**照抄原文骨架会丢掉"罚下者每帧 `stop()`"和"未就绪不进 active"的区分**。
- 【原文骨架 vs 本项目现状】原文 `_act_opp_kickoff`/`_act_ready` 都带 `store` 形参；当前 `src/main.py:169`、`src/main.py:178` 调用的是不带 `store` 的版本。改签名要同步改 `play()` 两处。
- 【经验建议】**把 `debugdraw` 当免费**：`debugdraw.flush()` 在帧末统一发一个 MarkerArray，每帧绘制量直接压在 33 ms 预算里；调试标签多到几十个时会影响帧率。

## 四、对本项目的具体改进建议

1. **`src/main.py:play()`**：把 `src/main.py:147-159` 的"活性自理"循环抽成模块级 `_collect_active(players) -> list[Player]`，`play()` 只保留"算 Phase + 画 phase 标签 + 调 `_collect_active` + 分派"四段。好处：`play()` 回到课程 02 描述的三步骨架，后续任何 `_act_*` 复用同一份过滤规则，不会出现"某分支忘了过滤罚下者"。
2. **`src/main.py:_analyze_and_draw` 与 `_draw_teammate_marker`**：在 `src/param.py` 新增 `DEBUG_DRAW = True`，两个函数首行 `if not DEBUG_DRAW: return`。理由：`runtime` 帧末 `debugdraw.flush()` 会把整帧 marker 打包下发，比赛/压测时应能一键关掉（**经验建议**，原文只说 `debugdraw.flush()` 在帧末，未提开关）。
3. **`src/main.py` 顶部 import**：把 3 处函数内 `from .framework import debugdraw`（`src/main.py:132`、`src/main.py:400`、`src/main.py:419`）改为模块级 `from .framework import debugdraw`。依据：`src/framework/debugdraw.py:12` 明确"没装（开发机无 ROS / 未 install）时所有绘制调用是 no-op，可安全在任意环境 import"，因此无 ROS 依赖、无循环导入风险，省掉每帧 3 次 import 查找。
4. **`src/main.py:_act_*` 签名统一**：把 `_act_opp_kickoff(context, players)`、`_act_ready(context, players)` 改为 `(context, players, store)`，与其余 4 个一致。课程 03 会反复用到"进入某阶段只执行一次"的边沿检测，签名不统一时加逻辑要回头改 `play()`。
5. **`src/param.py`**：新增 `CTRL_HZ_EXPECTED = 30.0` 与 `FRAME_BUDGET_WARN_MS = 50.0`，供 `_analyze_and_draw` 的帧耗时告警使用；不要从 `src/framework/config.py` import（那是平台配置，策略只读 `context.dt`）。
6. **`docs/kb/course/README.md`**：按课程 02 的"排障顺藤摸瓜"表补一节"现象 → 查哪个文件"，例如"看不到球 → `_build_context`/`RosSource`；踢球没反应 → `RobotBackend.kick`"（**经验建议**）。

## 五、原文关键摘录

> `framework/` 是基础设施，也就是厨房的水电网，没人天天改它，但缺了它后厨转不起来。`utils/` 是切菜、称重这些通用技能，谁做菜都能调用。`player.py` 是"厨师的操作手册"……`main.py` 是"主厨的管理手册"，决定谁去切、谁去翻、谁去摆盘。

> 策略越往上越贴近战术，越往下越通用。策略代码集中在上面两层，底层负责把意图变成行动……你可以大胆重写上层战术，而不用担心破坏下层。

> 机器人足球比赛节奏快，机器人需要高频响应指令。太慢（比如 5Hz），机器人会显得迟钝、追不上球；太快（比如 100Hz），单次决策时间不够、还浪费算力。30Hz 是实践中响应速度和计算量的平衡点。

> `play()` 被 `runtime` 以固定频率调用，就像被按了快门的相机——每 1/30 秒拍一张世界的照片（`Context`），并立刻决定这一下怎么动，然后等下一按。

| 原文给出的关键路径 | 位置 |
|---|---|
| 循环主体 | `src/framework/runtime.py` 的 `SoccerRuntime._loop()` / `_tick()` |
| 每帧构造感知 | `src/framework/runtime.py` 的 `_build_context()` |
| 调用决策 | `src/framework/runtime.py` 的 `self._agent.play()` |
| 控制频率配置 | `src/framework/config.py` 的 `SoccerConfig.control_hz` |
| 帧末可视化下发 | `runtime` 的 `debugdraw.flush()` |
| 踢球失败排查 | `src/framework/robot_backend.py` 的 `RobotBackend.kick` |

> 本质上，所有优化要么是在改写对 `Phase` 的理解，要么是在改写特定 `Phase` 分支中 `_act_*` 的逻辑。
