# 专题优化-移动与避障策略

真实比赛里，三个机器人挤成一团、被球挡住去路、一头撞上对方球门柱、或者绕着队友原地打转的情况比比皆是。这个模块拆解`walk_to`，让你了解怎么走位更聪明、怎么绕开障碍。

🎯 **学习目标**

- 看懂 `walk_to` 的走位逻辑
- 会调走位与避障参数

---

## 单元1：`walk_to` —— 遥控器的"导航键"

`Player` 最底层的接口 `set_velocity(vx, vy, vyaw)`——告诉机器人"朝哪个方向、以多快速度移动，同时转多快"。但实战里你几乎不会直接用 `set_velocity` 去导航，因为那意味着你要自己算方向、算距离、算到了没有。框架替我们封装了一个更省心的按钮：**`walk_to(target, ...)`**。

你可以把它理解成遥控器的"导航键"：你只说"去这个点"，它自己负责算出路线、避开障碍、判断到达。绝大多数战术里你都应该用 `walk_to`，把脑子留给"该去哪"而不是"怎么走过去"。

`walk_to` 定义在 `src/player.py`，它的完整签名是：

```Python
def walk_to(
    self,
    target: tuple[float, float],
    *,
    face: float | None = None,
    avoid_ball: bool = False,
    avoid_robots: bool = False,
    arrive_dist: float = ARRIVE_DIST,
) -> bool:
    """走向目标点。返回是否已到达。"""
```

- **`target`**：目标点坐标 `(x, y)`，单位是米，用的是第 4 篇讲过的**场地坐标系**（中圈原点，x 朝对方球门为正）。
- **`face`**：到达后（或近距离时）机器人**身体朝向**的角度，可选。比如你想让支援球员一边靠近接应点、一边始终面朝来球方向，就给它传 `face`。
- **`avoid_ball` / `avoid_robots`**：是否避开球 / 避开其他机器人。这是避障的总开关，默认**关闭**（走直线）。
- **`arrive_dist`**：到达阈值，默认取 `param.py` 里的 `ARRIVE_DIST`（0.15 米）。距离小于它就认为"到了"。

到达判定是 `walk_to` 的核心逻辑：

```Python
distance = math.hypot(target_x - pose.x, target_y - pose.y)
if distance < arrive_dist:
    if face is not None:
        err = normalize_angle(face - pose.theta)
        if abs(err) > 0.1:
            self.set_velocity(0.0, 0.0, self._angular(err))   # 原地转向到 face
        else:
            self.stop()                                        # 到位且朝向正确，停下
    else:
        self.stop()
    return True                                                # 已到达
```

这里藏着两个细节。其一，`arrive_dist` 用的是"到目标的直线距离"，不是"规划路径长度"，所以即使绕了远路，只要直线距离进了 0.15 米就停——这很合理，因为绕路是为了不撞，到了附近就该稳住。其二，如果传了 `face`，机器人会**先停在原地、只转身体**直到朝向误差小于 0.1 弧度（约 5.7°），再彻底停下；这对"射门前先摆正身体""守门员正对来球"这类场景至关重要。`return True` 还会被上层策略用来判断"这个球员是否到位了"，从而推进战术状态（比如开球时等三人全到位再启动）。

---

## 单元2：两段式走位控制

`walk_to` 不是简单地"朝目标发速度"。它会根据**离目标还有多远**，切换两种不同的行走模式——这就是"两段式走位"。

人形机器人通常优先前后行走，而不是横向。这是**效率和精度的权衡**。全向移动虽然灵活，但双足的机械特性决定了**沿前进方向走是最快、最稳的**，侧移和斜移的速度上限更低、控制误差更大。如果从球场一头走到另一头也全程侧移，不仅慢，还容易抖。

所以 `walk_to` 用一个阈值 `OMNI_DIST`（`param.py`）把走位分成两段：距离大于它时用"转身-走"模式，距离小于等于它时切换到全向模式。全向模式下，机器人可以不转身，直接横着、斜着、倒着移向目标，同时还能一边转身体朝向。

机器人在大多数移动中，行走控制主要负责计算出球员运动的线速度 `vx` 和角速度 `vyaw`。我们可以借助下图更清晰地理解行走控制和`OMNI_DIST`的关系

<whiteboard token="SqHPwSgsQhaWRVbSdljc8DlVnOe"></whiteboard>

行走控制逻辑如图所示：

- 对于 A，距离目标较远，且方向不对，会优先转向到朝向目标的方向，即变成B的状态；
- 对于 B，距离目标较远，但方向面对目标，可以以常规步态走向目标点，即变成C的状态；
- 对于C，距离目标点较近，进入 `OMNI_DIST` 范围，但还未被判定为到达，机器人会切换到全向模式调整到目标位姿。

总结一下，上述状态不割裂，球员会持续关注自己的位姿状态，并依次进入 A/B/C 状态直到处于目标状态，完成 `walk_to` 命令。

---

## 单元3：双层避障（全局 A\\\* + 局部 VFH）

现在到了本篇的核心。当你打开 `avoid_ball` 或 `avoid_robots` 时，`walk_to` 会启动一套**双层避障**：先尝试用全局 A\\\* 规划一条绕开所有障碍的完整路线；如果全局规划失败（比如被完全堵死），就退回局部 VFH 做"眼前这一步往哪拐"的反应式避让。

### 障碍从哪来：`collect_obstacles`

避障的第一步是"知道周围有什么障碍"。框架用 `collect_obstacles` 把场景里的东西收集成一组**圆形障碍物**：

```Python
obstacles = collect_obstacles(
    self.context, self.id,
    ball=avoid_ball, robots=avoid_robots,
    goals=(avoid_ball or avoid_robots),
)
```

注意三个开关的对应关系：`ball=avoid_ball` 表示"要避球才把球当障碍"；`robots=avoid_robots` 表示"要避机器人就把双方机器人都当障碍"；而 `goals=(avoid_ball or avoid_robots)` 很巧妙——只要开启了任意一种避障，就把**球门结构也建模成障碍**（门柱、球网），防止机器人一头撞进球门柱。每个障碍是一个圆，带半径——半径来自 `param.py` 里的 `BALL_OBSTACLE_RADIUS`、`OPPONENT_RADIUS`、`TEAMMATE_RADIUS` 等。

### 全局层：A\* 栅格规划（`plan_global_path`）

全局层在 `src/utils/path_planner.py`，用一张铺满整个场地的 8 邻接栅格做 A\* 搜索。

> A\*（A-Star）算法是一种用于图形搜索和路径规划的经典启发式算法。它结合了 Dijkstra 算法（保证找到最短路径）和最佳优先搜索（定向朝着终点探索）的优势，能够在网格或地图中极高效地找到从起点到终点的最短路径。

核心循环如下：

```Python
def plan_global_path(context, start, target, obstacles):
    # 1) 以场地为界建栅格，分辨率 = GLOBAL_GRID_RESOLUTION_M
    # 2) 把障碍按 GLOBAL_OBSTACLE_MARGIN_M 膨胀后标记为"不可走"
    # 3) A* 从 start 搜到 target
    while open_heap:
        _, _, current = heapq.heappop(open_heap)
        if current == goal_idx:
            return _reconstruct(came_from, current, ...)   # 回溯出整条路径
        for neighbor, step_cost in _neighbors(current):
            if _blocked(neighbor, obstacles):
                continue                                    # 撞障碍的格子不要
            tentative = g_score[current] + step_cost
            if tentative < g_score.get(neighbor, inf):
                came_from[neighbor] = current
                g_score[neighbor] = tentative
                heapq.heappush(open_heap, (tentative + _heuristic(...), ...))
    return None                                             # 搜不到路
```

 A\\\* 的精髓在 `tentative + _heuristic` 这一项：前半段 `g_score` 是"从起点实际走过的代价"，后半段 `_heuristic`（欧氏距离）是"到目标的估计代价"。两者相加让搜索既不会乱撞、也不会只顾眼下，总能优先朝目标方向扩展。栅格分辨率 `GLOBAL_GRID_RESOLUTION_M`（0.35 米/格）越小，路径越平滑但计算越重；障碍膨胀 `GLOBAL_OBSTACLE_MARGIN_M`（0.10 米）是在障碍半径上再外扩一点，留安全余量。搜不到路时返回 `None`，这时上面代码就会退回局部 VFH——这就是"双层"的兜底设计。

### 局部层：VFH 风格的方向扫描（`_plan_heading`）

当全局规划不可用，或你直接关闭 `USE_GLOBAL_PATH_PLANNER` 时，`walk_to` 用局部 VFH 决定"这一步朝哪走"。

> 局部矢量场直方图（Vector Field Histogram, 简称 VFH） 是一种专门用于移动机器人局部避障与路径规划的经典算法。
> 
> 如果说 A\* 算法 负责“全局规划”（在已知地图上画出从起点到终点的整条路线），那么 VFH 就负责“局部避障”（在机器人移动过程中，实时根据传感器数据绕开未知的障碍物）。

它围绕机器人扫一圈候选方向，选最朝目标、且前方够空的那一个：

```Python
def _plan_heading(self, pose, goal_dir, obstacles):
    sign_first = 1.0 if self.id % 2 == 0 else -1.0   # 用 id 奇偶打破对称
    offsets = [0.0]
    k = 1
    while k * PLAN_STEP <= PLAN_MAX_OFFSET + 1e-9:    # 从目标方向向两侧扫
        offsets.append(sign_first * k * PLAN_STEP)
        offsets.append(-sign_first * k * PLAN_STEP)
        k += 1
    for off in offsets:
        h = goal_dir + off
        clear = _heading_clearance(pose.x, pose.y, h, obstacles)
        # 选"最朝目标(off 小) 且 前方余量 >= PLAN_CLEARANCE"的方向
        ...
```

这段最妙的设计是 `sign_first` 用 `player_id` 的**奇偶性**决定先往左扫还是先往右扫。两个机器人正对同一个障碍冲过去时，如果它们扫描顺序完全一样，会同时往同一侧躲，结果在侧面又撞一起。用奇偶错开，一个偏左、一个偏右，自然分流。`PLAN_STEP`（15°）是扫描步长，`PLAN_MAX_OFFSET`（±100°）是最大能偏离目标方向多少，`PLAN_CLEARANCE`（0.35 米）是候选方向前方必须保留的最小空隙。`_heading_clearance` 则沿该方向发射一条 `PLAN_LOOKAHEAD`（1.2 米）长的探测射线，量出"到最近障碍还有多远"。

### 多层串联

把上面拼起来，就是 `walk_to` 规划分支的完整逻辑：

```Python
goal_dir = math.atan2(dy, dx)
planned_path = None
if (avoid_ball or avoid_robots) and self.context is not None:
    obstacles = collect_obstacles(self.context, self.id,
                                  ball=avoid_ball, robots=avoid_robots,
                                  goals=(avoid_ball or avoid_robots))
    if USE_GLOBAL_PATH_PLANNER:
        planned_path = plan_global_path(self.context, (pose.x, pose.y), (tx, ty), obstacles)
        if planned_path is not None:
            waypoint = self._path_waypoint(pose, planned_path)        # 取前方路径点
            heading = angle_to(pose.x, pose.y, waypoint[0], waypoint[1])
        else:
            heading = self._plan_heading(pose, goal_dir, obstacles)   # 全局失败退回局部
    else:
        heading = self._plan_heading(pose, goal_dir, obstacles)
else:
    heading = goal_dir                                               # 不避障：直奔目标
```

`walk_to` 决策流程图

这张图的箭头代表**优先级**。能直走就直走；要避障就先上全局 A\*；全局搜不到才退回局部 VFH。全局规划成功后，`heading` 指向的是**路径上的下一个路点**，而不是最终目标，这样才能真正绕开障碍。

---

## 单元4：走位与避障参数调优清单

所有相关参数都集中在 `src/param.py`。按影响分成四组：

| 参数 | 默认值 | 控制什么 | 调整效果 |
|-|-|-|-|
| `ARRIVE_DIST` | 0.15 m | 到达阈值 | 调大→更早停（站位更松）；调小→贴得更紧 |
| `OMNI_DIST` | 1.0 m | 全向/转身切换距离 | 调大→更多"边走边转"（更灵活但可能晃）；调小→更早进入"先转身再走" |
| `TURN_THRESHOLD` | 0.5 rad | 先转身的角度门槛 | 调大→更敢斜着冲；调小→更爱先对齐再走 |
| `MAX_LINEAR` | 2.0 m/s | 最大线速度 | 调大→走得更快（但可能刹不住/更晃） |
| `LINEAR_GAIN` | 1.5 | 平移 P 增益 | 调大→接近更快、更"急"；调小→更柔 |
| `ANGULAR_GAIN` | 2.0 | 转向 P 增益 | 调大→转得更快更猛 |
| `PLAN_LOOKAHEAD` | 1.2 m | 局部探测射线长度 | 调大→提前发现障碍（更稳）；调小→反应更迟 |
| `PLAN_CLEARANCE` | 0.35 m | 局部最小安全余量 | 调大→离障碍更远（更保守）；调小→贴更近 |
| `PLAN_STEP` | 15° | 局部扫描步长 | 调小→方向更精细（路径更顺）；调大→更快但更糙 |
| `PLAN_MAX_OFFSET` | 100° | 局部最大偏转 | 调大→能绕更大弯；调小→更"认死理"直奔 |
| `USE_GLOBAL_PATH_PLANNER` | True | 是否启用全局 A\\\* | False→只用局部 VFH（更轻量但路径更差） |
| `GLOBAL_GRID_RESOLUTION_M` | 0.35 m | 栅格分辨率 | 调小→路径更平滑（更慢）；调大→更快更糙 |
| `GLOBAL_OBSTACLE_MARGIN_M` | 0.10 m | 障碍膨胀余量 | 调大→绕得更远（更安全） |
| `BALL_OBSTACLE_RADIUS` | 0.5 m | 球的障碍半径 | 调大→更不敢贴球（追球更难） |
| `OPPONENT_RADIUS` | 0.55 m | 对手机器人半径 | 调大→躲对手更远 |
| `TEAMMATE_RADIUS` | 0.48 m | 队友机器人半径 | 调大→队友间分得更开（防挤） |

典型调参场景

| **现象** | **调整参数** | **说明 / 补充** |
|-|-|-|
| 机器人总是撞墙 / 撞门柱 | PLAN_CLEARANCE → 0.5  <br/>GLOBAL_OBSTACLE_MARGIN_M → 0.15 | 确认 walk_to 调用时开启了 avoid_robots 或 avoid_ball（球门障碍依赖这两个开关之一） |
| 绕路绕得太远、太慢 | GLOBAL_GRID_RESOLUTION_M → 0.25  <br/>PLAN_STEP → 10°  <br/>PLAN_MAX_OFFSET → 60° | 前两项让路径更贴最优；最后一项限制乱拐幅度 |
| 两个机器人迎面卡住、互相顶 | TEAMMATE_RADIUS → 0.55 | 先检查是否忘了用奇偶分流（框架已内置在 \_plan_heading）；调大半径给彼此留空间 |
| 到了点还不停、来回抖 | ARRIVE_DIST → 0.2  <br/>LINEAR_GAIN → 1.2 | 前者增大到达判定距离，后者让减速更柔和 |

> 此步骤可借助AI Assistant完成，参考提示词：“两个机器人迎面卡住”，帮我定位参数并调整，改善问题。

---

## 扩展阅读

- A\\\* 寻路算法（本项目 `utils/path_planner.py` 即 A\\\* 栅格规划）：[https://en.wikipedia.org/wiki/A\\\*\_search_algorithm](https://en.wikipedia.org/wiki/A*_search_algorithm)
- VFH 向量场直方图（本项目 `_plan_heading` 的思想来源）：Borenstein & Koren, \*The Vector Field Histogram\*（1991），[论文链接](https://cris.technion.ac.il/en/publications/the-vector-field-histogramfast-obstacle-avoidance-for-mobile-robo)

---

## 要点总结

- `walk_to` 是推荐的导航方式，比手写 `set_velocity` 省心且更稳；
- 走位是**两段式**的：远距离先转身再走，近距离全向边走边转；
- 避障是**双层**的：优先全局 A\*，失效时退回局部 VFH，并用 `id` 奇偶打破对称防互顶；
- 调参时先确认症状，使用表格找到对应参数，再小步验证。