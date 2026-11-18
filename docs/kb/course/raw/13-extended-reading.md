# 补充-扩展阅读与资源

这篇是本项目的补充资源：官方文档、赛事规则、算法经典出处、足球战术解析、调试实践，已按主题分好类。不用从头读，收藏起来，写策略卡壳时回来找，哪里不会点哪里。

## 一、官方资源

- [Booster 官方文档中心](https://docs.booster.tech/zh-CN/)
- 策略调试工具：

  <source name="战术板-策略调试工具.html" mime="text/html" size="17783" token="HoZJbb6LvofQsNxKvgbcLBlOnzc"/>

---

## 二、赛事规则

- [**RoboCup 官网**](https://www.robocup.org/)：赛事背景、规则演进、各组别介绍，以及"2050 年机器人战胜人类冠军队"的终极目标
- [**RoboCup 标准平台组规则**](https://ssl.robocup.org/rules)：规则、场地规格的来源
- [**RoboCup Sim 3D 规则 PDF**](https://ssim.robocup.org/wp-content/uploads/2024/05/Rules_RoboCupSim3D2024.pdf)：死球、开球、任意球规则的权威来源，想深挖"开球能否直接得分""死球须在几秒内发出"等细节时查阅

---

## 三、核心技术主题

### 3.1 行为建模

- [**有限状态机 FSM**](https://en.wikipedia.org/wiki/Finite-state_machine)：本教程第 3 篇的核心模型，Wikipedia 图文入门
- [**行为树 Behavior Tree**](https://en.wikipedia.org/wiki/Behavior_tree_(artificial_intelligence,_robotics_and_control))：另一种组织复杂决策的方式

### 3.2 坐标

- [**ROS** ](http://wiki.ros.org/tf)[**`tf`**](http://wiki.ros.org/tf)[ **坐标变换**](http://wiki.ros.org/tf)：理解"统一坐标系"为何能省一半代码
- [**向量与线性代数入门**](https://www.khanacademy.org/math/linear-algebra/vectors-and-spaces)：点积、投影（本项目 `block_path_projection`、`_heading_clearance` 都用到了），Khan Academy 的免费图文教程

### 3.3 避障与路径规划

- [**A\\\* 寻路算法**](https://en.wikipedia.org/wiki/A*_search_algorithm)：本项目 `utils/path_planner.py` 的 `plan_global_path` 即 8 邻接栅格 A\\\*，Wikipedia 图文讲解其原理
- [**VFH 向量场直方图（Technion 论文页）**](https://cris.technion.ac.il/en/publications/the-vector-field-histogramfast-obstacle-avoidance-for-mobile-robo)：Borenstein & Koren（1991），本项目 `_plan_heading` 的思想来源
- [**VFH 论文 PDF 直读**](https://ykoren.engin.umich.edu/wp-content/uploads/sites/122/2014/05/1Real-time-obstacle-avoidance-for-fast-mobile-robots-in-cluttered-environments.pdf)：上述论文的全文 PDF
- [**DWA 动态窗口法原论文**](https://www.ri.cmu.edu/pub_files/pub1/fox_dieter_1997_1/fox_dieter_1997_1.pdf)：Fox, Burgard & Thrun（1997），比 VFH 更平滑的在线避障，是升级本项目反应式控制的常用方向

### 3.4 多智能体协同

- [**多智能体系统**](https://en.wikipedia.org/wiki/Multi-agent_system)：角色分配、编队控制、任务分配的全局知识入门
- [**编队控制**](https://en.wikipedia.org/wiki/Formation_control)：保持三角形/菱形阵型的理论基础
- [**分布式共识**](https://en.wikipedia.org/wiki/Consensus_(computer_science))：多机器人信息共享与协同决策的数学基础（本项目目前未涉及机器人间通讯，此处为进阶方向）

### 3.5 机器学习

- [**OpenAI Spinning Up 强化学习教程**](https://spinningup.openai.com/en/latest/)：公认最好的 RL 入门资料，从基础概念到代码实战
- [**卡尔曼滤波**](https://en.wikipedia.org/wiki/Kalman_filter)：轨迹预测的经典工具，结合第 6 篇的 `store` 缓存历史球速，可实现球去向的平滑预测

---

## 四、足球战术

- [**区域防守 Zonal Marking 解析**](https://www.teamstats.net/blog/zonal-marking-football)：Zonal marking 在定位球与运动战中的应用，直接可翻译为联防逻辑
- [**高位逼抢 High Press 详解**](https://en.wikipedia.org/wiki/Pressing_(association_football))："什么时候压上、什么时候回收"分区策略（专题优化3）的战术思想来源
- [**高中低三道防守阵型**](https://footballcoach365.com/3-types-of-blocks-how-to-defend-zonal-marking)：图文讲清 high/mid/low block 三种防守姿态的取舍
- [**区域盯人 Zonal Marking 详解**](https://guidetofootball.com/tactics/zonal-marking)："守区域而非盯人"的现代防守思想，对应分区联防

---

## 五、调试与工程实践

- [**Python** ](https://docs.python.org/3/library/logging.html)[**`logging`**](https://docs.python.org/3/library/logging.html)[ **官方文档**](https://docs.python.org/3/library/logging.html)：理解 `framework/agent.py` 中日志桥接的原理
- [**Mermaid 图表语法**](https://mermaid.js.org/)：本教程所有图都用 Mermaid 绘制，在 VS Code / Booster Studio / GitHub 均可渲染，学会它就能自己画决策图辅助调试
- [**Python** ](https://docs.python.org/3/library/types.html#types.SimpleNamespace)[**`SimpleNamespace`**](https://docs.python.org/3/library/types.html#types.SimpleNamespace)[ **官方文档**](https://docs.python.org/3/library/types.html#types.SimpleNamespace)：理解 `store` 容器的本质