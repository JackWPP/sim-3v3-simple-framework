# 13 附录B 补充-扩展阅读与资源
> 来源：https://booster.feishu.cn/wiki/IfsrwODDkijFbtkcZwycKLesnHg（原文约 3500 字）

## 一、战术剧本 / 核心要点

本篇不是战术，是**索引**：把前面 12 篇里"点到为止"的概念各给一个权威出处，并按主题分好类。原文的用法是"不用从头读，收藏起来，写策略卡壳时回来找，哪里不会点哪里"——所以这里按"卡壳症状 → 该查哪条 → 对应本项目哪个文件"重排。

- **官方资源（第 1 节）**：Booster 官方文档中心 `docs.booster.tech/zh-CN/` 是接口与平台的唯一权威；另有一个**策略调试工具**，原文以 html 附件形式嵌入（`战术板-策略调试工具.html`，约 17.7 KB），**原文未说明该工具的具体用法**，只列为"策略调试工具"。
- **赛事规则三条线（第 2 节）**：RoboCup 官网给背景与"2050 年机器人战胜人类冠军队"的终极目标；RoboCup 标准平台组规则 `ssl.robocup.org/rules` 是**规则与场地规格的来源**；**RoboCup Sim 3D 2024 规则 PDF 是死球、开球、任意球规则的权威来源**。原文明确指出的使用场景是：想深挖"**开球能否直接得分**""**死球须在几秒内发出**"这类细节时查它——这两条恰好就是本项目 `_act_our_kickoff`（开球后 0.5 m 才可射门）与定位球分支最容易踩线的地方。
- **行为建模（3.1）**：FSM 是**本教程第 3 篇的核心模型**（即本项目 `Phase` 状态机 `get_phase`），行为树是"另一种组织复杂决策的方式"。原文没有说本项目要用行为树，仅作对照。
- **坐标（3.2）**：ROS `tf` 用来理解"**统一坐标系为何能省一半代码**"——本项目已由框架把坐标转成本队视角，这一节正是解释为什么 `utils/geom.py` 不需要镜像代码；Khan Academy 的向量/线性代数入门对应**点积与投影**，原文点名本项目 `block_path_projection`、`_heading_clearance` **两处都用到了**。
- **避障与路径规划（3.3）**：三条线索指向本项目同一处代码的三个层次——A\*（`utils/path_planner.py` 的 `plan_global_path`，即 **8 邻接栅格 A\***）、VFH（`_plan_heading` 的**思想来源**，Borenstein & Koren 1991）、DWA（Fox, Burgard & Thrun 1997，"**比 VFH 更平滑的在线避障，是升级本项目反应式控制的常用方向**"）。
- **多智能体（3.4）**：多智能体系统给"角色分配、编队控制、任务分配"的全局视角；编队控制是"保持三角形/菱形阵型的理论基础"；分布式共识是信息共享的数学基础，**原文明确注明：本项目目前未涉及机器人间通讯，此处为进阶方向**——即现阶段不要指望靠通讯解决配合，只能靠"每帧各自看同一份 `context` 做出一致决策"。
- **机器学习（3.5）**：Spinning Up 是 RL 入门；卡尔曼滤波被原文指定了一个具体落点——"**结合第 6 篇的 `store` 缓存历史球速，可实现球去向的平滑预测**"。这是全篇唯一一条"某算法 + 某文件 + 某用途"的完整链路。
- **足球战术（第 4 节）**：zonal marking（teamstats.net、guidetofootball.com 两篇）"直接可翻译为联防逻辑"，是第 10/11 篇区域联防的思想来源；high press 是"**什么时候压上、什么时候回收**"的分区策略（第 11 篇）的战术思想来源；high/mid/low block 三型讲三种防守姿态的取舍——对应本项目"丢球后整队回收到哪条横线"。
- **工程实践（第 5 节）**：Python `logging` 文档对应"理解 `framework/agent.py` 中日志桥接的原理"；Mermaid 是"教程所有图"的绘制语言，原文建议"学会它就能自己画决策图辅助调试"；`SimpleNamespace` 文档对应"理解 `store` 容器的本质"。

## 二、代码与公式

**（1）原文给出的"本项目模块 ↔ 算法"对照（唯一可直接落地的映射表，出自 3.2/3.3/3.5）**

| 本项目位置 | 对应算法/概念 | 原文原话 |
|---|---|---|
| `src/main.py:get_phase`（`Phase` 状态机） | FSM | "本教程第 3 篇的核心模型"（3.1） |
| `src/utils/path_planner.py:plan_global_path` | A\*，**8 邻接栅格** | "即 8 邻接栅格 A\*"（3.3） |
| `src/player.py:block_path_projection` | 向量点积 / 投影 | "点积、投影（本项目 `block_path_projection`、`_heading_clearance` 都用到了）"（3.2） |
| `src/player.py:_heading_clearance` | 同上 | 同上 |
| `src/player.py:_plan_heading` | VFH | "本项目 `_plan_heading` 的思想来源"（3.3） |
| `store`（`init_store` 写入的历史球速） | 卡尔曼滤波 | "结合第 6 篇的 `store` 缓存历史球速，可实现球去向的平滑预测"（3.5） |
| `framework/agent.py` 日志桥接 | Python `logging` | "理解 `framework/agent.py` 中日志桥接的原理"（第 5 节） |

**（2）原文点名的两条"升级方向"（不是代码，是路线，写在这里备查）**

- 反应式避障：`_plan_heading`（VFH）→ **DWA**（原文："比 VFH 更平滑的在线避障，是升级本项目反应式控制的常用方向"）。
- 球位置预测：`store` 里的历史球速 → **卡尔曼滤波**平滑预测（原文："可实现球去向的平滑预测"）。

**（3）【非原文·标准定义】投影公式**：`block_path_projection` 与 `_heading_clearance` 用的点积/投影，其标准形式为 `proj = ((P-A)·(B-A)) / |B-A|`（得到 P 在直线 AB 上的投影长度），垂直距离 `d = |(P-A) - proj·û|`。**原文只说了这两个函数用到点积/投影，未给公式**；此式仅用于读代码时对号入座。

**（4）规则细节的查阅入口**（原文第 2 节）：`https://ssim.robocup.org/wp-content/uploads/2024/05/Rules_RoboCupSim3D2024.pdf`。原文明确它覆盖"死球、开球、任意球规则"，是"开球能否直接得分""死球须在几秒内发出"的权威来源。**原文未摘录任何具体秒数或条款编号。**

## 三、易错点与规则红线

- 【原文】3.4 节明确"**本项目目前未涉及机器人间通讯**"。任何依赖"队友广播位置/状态"的设计都超出当前能力，只能靠 `context` 里三方共享的同一帧快照做一致性决策；跨帧记忆只能各自写 `store`。
- 【原文】A\* 那一条限定为"**8 邻接栅格**"，不是 4 邻接也不是任意图搜索；对照 Wikipedia 条目优化时不要换成连续空间版本，否则与 `GLOBAL_GRID_RESOLUTION_M = 0.35` 的栅格模型冲突。
- 【原文】VFH 只被描述为"**思想来源**"，不是"本项目完整实现了 VFH"。原文没有声称 `_plan_heading` 具备 VFH 的直方图/阈值极化等完整机制——**原文未明确**其与本项目实现的差异程度。
- 【原文】DWA 是"**常用方向**"，不是"应该做"。原文没有给出任何 DWA 参数或效果对比数据。
- 【原文】卡尔曼滤波那条的前提是"**第 6 篇的 `store` 已缓存历史球速**"。若 `store` 里没有历史球速，这条链路不成立——**原文未明确**该缓存是否已在本项目实现（据代码核查：`init_store` 当前未初始化任何球速字段）。
- 【原文】"战术板-策略调试工具.html"仅以附件形式列出，**原文未说明其功能、用法与运行方式**。
- 【经验建议】本篇的价值不在"读到什么"，而在"**别自己去猜规则**"：凡涉及"开球直接得分是否有效""死球后几秒内必须发出""避让距离"的判定，优先查 Sim 3D 2024 规则 PDF 与技能里的 3v3 规则，而不是靠试错。
- 【经验建议】资源列表容易变成"收藏了但没看"。建议只挑与当前改动相关的 1 条，改完再换下一条，避免同时引入 A\* 重写 + DWA + 卡尔曼三件事。

## 四、对本项目的具体改进建议

按"投入产出比"从高到低排，全部可在现有文件内完成，**不需要新增依赖**。

1. **`src/utils/path_planner.py`：先对齐 A\* 标准实现，再谈优化**（对应 3.3 第 1 条）。检查三点：① `_heuristic` 是否为欧氏距离（8 邻接必须配欧氏距离，配曼哈顿会让路径贴成锯齿）；② `g_score` 是否用 `sqrt(2)` 作为对角步代价（8 邻接的经典错误是全用 1.0，导致路径偏斜）；③ `_reconstruct` 是否每步都在 `came_from` 里查父节点。这三项是 Wikipedia A\* 条目的标准内容，**原文只给了"8 邻接栅格 A\*"这一句定性描述**。
2. **`src/player.py:_plan_heading` 升级 DWA（可选，改动最大）**（对应 3.3 第 4 条）。原文只说 DWA 是"升级反应式控制的常用方向"，未给参数。若要落地，`param.py` 需新增具名常量：`DWA_MAX_V = 0.8`、`DWA_MAX_W = 1.5`、`DWA_V_SAMPLES = 7`、`DWA_W_SAMPLES = 15`、`DWA_HORIZON_S = 0.6`、`DWA_DT_S = 0.1`、`DWA_WEIGHT_HEADING = 1.0`、`DWA_WEIGHT_CLEARANCE = 1.2`、`DWA_WEIGHT_VELOCITY = 0.4`、`DWA_OBSTACLE_MARGIN_M = 0.35`。**这些数值原文完全未给，属自拟起点值，必须在仿真里重新整定。**
3. **`src/player.py:guard` 用预测落点替代当前球位**（对应 3.5 卡尔曼那条，投入产出比最高的一处战术收益）。做法：`init_store` 里初始化 `store.ball_vx = 0.0`、`store.ball_vy = 0.0`、`store.prev_ball = None`；每帧用 `(ball - prev_ball) / dt` 得到瞬时速度并做一阶低通（`param.py` 增 `BALL_VEL_ALPHA = 0.35`）；`guard()` 把站位目标从 `own_goal_area_center` 改为"**球位置 + 球速 × `BALL_PREDICT_HORIZON_S`** 在自家球门线上的截距，再钳到门柱内侧"。`BALL_PREDICT_HORIZON_S = 0.45`（原文未给，自拟）。注意 `context.ball` 约 **1.5 s** 不更新就变 `None`，此时必须退回"站门区中央"，不能继续用速度外推。
4. **`src/main.py` 增"高/中/低 block"三档回撤线**（对应第 4 节 footballcoach365 那条）。在 `_act_normal` 开头算 `ball.x`，选档：`ball.x > PRESS_X` → 高压（attacker 出脚、其余两人前压至中点）；`DANGER_X < ball.x <= PRESS_X` → 中位；`ball.x <= DANGER_X` → 低位（support 退到禁区弧顶、guard 回门线）。`param.py` 新增：`PRESS_X = 2.0`、`MID_X = -1.0`、`DANGER_X = -3.5`（**半场长度 7.0 m**，全部取在 ±7 内且留 0.5 m 余量；数值为自拟，原文未给）。**注意：这套"按球 x 分档"与第 11 篇的分区策略是同一思想的粗粒度版**，若已按 11 篇实现区域机，则不要重复搭一套，直接把 block 档位作为区域机的一个输出。
5. **`src/main.py:_analyze_and_draw` 是当前唯一的"日志"**（对应第 5 节 logging 那条）：`framework/agent.py` 不可改，场上 `id:action` 标签就是最轻量的观测通道。建议把 block 档位也拼进标签（如 `phase=NORMAL block=high`），这样一屏就能看出整队处于哪一档，比查日志快。
6. **`docs/kb/` 下补两张 Mermaid 决策图**（对应第 5 节 Mermaid 那条）：一张 `_act_our_set_play` 的球种分支图（THROW_IN / CORNER_KICK / GOAL_KICK / DIRECT_FREE_KICK / INDIRECT_FREE_KICK / PENALTY_KICK），一张 `_act_opp_set_play` 的人墙+包夹+区域分工图。原文说"学会它就能自己画决策图辅助调试"——改定位球分支前先画图，能提前发现漏掉的球种（现有代码就漏了 3 个 `SetPlay` 取值）。
7. **`store` 的读写纪律**（对应第 5 节 `SimpleNamespace` 那条）：`SimpleNamespace` 没有 `get`/`set`，一律 `getattr(store, "name", default)` 读、属性赋值写；新字段必须在 `init_store`（`src/main.py:115`）里给初值，否则第一帧 `getattr` 的默认值与后续类型不一致。这是 3.5 卡尔曼方案能跑起来的前提。

## 五、原文关键摘录

> 这篇是本项目的补充资源：官方文档、赛事规则、算法经典出处、足球战术解析、调试实践，已按主题分好类。不用从头读，收藏起来，写策略卡壳时回来找，哪里不会点哪里。

> **RoboCup Sim 3D 规则 PDF**：死球、开球、任意球规则的权威来源，想深挖"开球能否直接得分""死球须在几秒内发出"等细节时查阅。

> **A\* 寻路算法**：本项目 `utils/path_planner.py` 的 `plan_global_path` 即 8 邻接栅格 A\*。

> **VFH 向量场直方图**：Borenstein & Koren（1991），本项目 `_plan_heading` 的思想来源。

> **DWA 动态窗口法原论文**：Fox, Burgard & Thrun（1997），比 VFH 更平滑的在线避障，是升级本项目反应式控制的常用方向。

> **分布式共识**：多机器人信息共享与协同决策的数学基础（本项目目前未涉及机器人间通讯，此处为进阶方向）。

> **卡尔曼滤波**：轨迹预测的经典工具，结合第 6 篇的 `store` 缓存历史球速，可实现球去向的平滑预测。

> **高位逼抢 High Press 详解**："什么时候压上、什么时候回收"分区策略（专题优化3）的战术思想来源。

> **Mermaid 图表语法**：本教程所有图都用 Mermaid 绘制，在 VS Code / Booster Studio / GitHub 均可渲染，学会它就能自己画决策图辅助调试。

**25 条资源清单（原文第 1–5 节全量，按主题）**

| 主题 | 资源 | 原文给的一句话定位 |
|---|---|---|
| 官方 | Booster 官方文档中心 | `docs.booster.tech/zh-CN/` |
| 官方 | 战术板-策略调试工具.html | 以附件嵌入，**原文未说明用法** |
| 规则 | RoboCup 官网 | 背景、规则演进、"2050 年战胜人类冠军队" |
| 规则 | RoboCup 标准平台组规则 | 规则、场地规格的来源 |
| 规则 | RoboCup Sim 3D 规则 PDF | 死球/开球/任意球权威来源 |
| 建模 | FSM（Wikipedia） | 第 3 篇核心模型 |
| 建模 | 行为树（Wikipedia） | 另一种组织复杂决策的方式 |
| 坐标 | ROS `tf` | 解释"统一坐标系省一半代码" |
| 坐标 | Khan Academy 向量 | 点积、投影 |
| 规划 | A\*（Wikipedia） | 8 邻接栅格 A\* |
| 规划 | VFH（Technion 页 + PDF 全文） | `_plan_heading` 思想来源 |
| 规划 | DWA 原论文 PDF | 更平滑的在线避障，升级方向 |
| 协同 | 多智能体系统 | 角色分配、编队、任务分配入门 |
| 协同 | 编队控制 | 保持三角/菱形阵型的理论基础 |
| 协同 | 分布式共识 | 需机器人间通讯，进阶 |
| ML | Spinning Up（OpenAI） | RL 入门 |
| ML | 卡尔曼滤波 | 配合 `store` 历史球速做球去向预测 |
| 战术 | Zonal Marking（teamstats.net） | 定位球与运动战中的联防逻辑 |
| 战术 | High Press（Wikipedia） | 压上/回收时机，分区策略思想来源 |
| 战术 | high/mid/low block（footballcoach365） | 三种防守姿态的取舍 |
| 战术 | Zonal Marking（guidetofootball.com） | "守区域而非盯人" |
| 工程 | Python `logging` | `framework/agent.py` 日志桥接原理 |
| 工程 | Mermaid | 教程所有图，可自绘决策图 |
| 工程 | `SimpleNamespace` | `store` 容器本质 |
