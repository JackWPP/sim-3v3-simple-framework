# 12 专题优化-移动与避障策略
> 来源：https://booster.feishu.cn/wiki/OfYBwkQCfib75bkHhBhc5NRxnWb（原文约 9000 字）

## 一、战术剧本 / 核心要点

- **为什么不用 `set_velocity` 导航**【原文】：`set_velocity(vx, vy, vyaw)` 要自己算方向、算距离、算到没到；`walk_to` 是"导航键"，你只说"去这个点"，它负责算路线、避障、判断到达。绝大多数战术都该用 `walk_to`，把脑子留给"该去哪"。
- **`walk_to` 完整签名**【原文】：

```python
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

- **四个参数语义**【原文】：`target` 是场地坐标（米，中圈原点，x 朝对方球门为正）；`face` 是到达后（或近距离时）的身体朝向角，想让支援球员"一边靠近接应点、一边始终面朝来球方向"就传它；`avoid_ball` / `avoid_robots` 是避障总开关，**默认关闭（走直线）**；`arrive_dist` 默认取 `ARRIVE_DIST`（**0.15 m**），距离小于它就认为"到了"。
- **到达判定的两个细节**【原文】：① `arrive_dist` 用的是"到目标的**直线**距离"而不是"规划路径长度"，绕了远路只要直线距离进 0.15 m 就停——合理，因为绕路是为了不撞，到了附近就该稳住；② 传了 `face` 时机器人会**先停在原地、只转身体**，直到朝向误差小于 **0.1 弧度（约 5.7°）** 才彻底停下，这对"射门前先摆正身体""守门员正对来球"至关重要；③ `return True` 被上层用来判断"这个球员是否到位"，从而推进战术状态（比如开球时等三人全到位再启动）。
- **两段式走位（A→B→C）**【原文】：人形机器人优先**前后**行走，这是效率和精度的权衡——全向移动虽灵活，但双足机械特性决定沿前进方向走最快最稳，侧移和斜移的速度上限更低、控制误差更大，全程侧移不仅慢还容易抖。因此用 `OMNI_DIST`（**1.0 m**）把走位切成两段：距离 > 它时"转身-走"，≤ 它时切全向模式（不转身，直接横着/斜着/倒着移向目标，同时还能转身体朝向）。
  - A：距离远且方向不对 → 优先原地转向到朝目标（变成 B）。
  - B：距离远但已面向目标 → 常规步态走向目标（变成 C）。
  - C：进入 `OMNI_DIST` 范围但未判定到达 → 切全向模式调整到目标位姿。
  - 三者不割裂，球员持续关注自身位姿，依次进入 A/B/C 直到目标。
- **双层避障**【原文】：打开 `avoid_ball` 或 `avoid_robots` 时，先尝试**全局 A\*** 规划完整绕障路线；全局失败（被完全堵死）才退回**局部 VFH** 做"眼前这一步往哪拐"的反应式避让。这就是"双层"兜底设计。
- **障碍来源 `collect_obstacles`**【原文】：把场景收集成一组**圆形**障碍物。三个开关对应关系——`ball=avoid_ball`（要避球才把球当障碍）、`robots=avoid_robots`（避机器人时把**双方**机器人都当障碍）、`goals=(avoid_ball or avoid_robots)`（只要开任意一种避障就把**球门结构**建模成障碍：门柱、球网，防止一头撞进球门柱）。半径来自 `param.py` 的 `BALL_OBSTACLE_RADIUS`、`OPPONENT_RADIUS`、`TEAMMATE_RADIUS`。
- **全局层 A\* 栅格**【原文】：铺满整个场地的 **8 邻接**栅格，把障碍按 `GLOBAL_OBSTACLE_MARGIN_M` 膨胀后标记"不可走"，从 start 搜到 target 后回溯整条路径。精髓在 `tentative + _heuristic`：`g_score` 是"从起点实际走过的代价"，`_heuristic`（欧氏距离）是"到目标的估计代价"，两者相加让搜索既不会乱撞、也不会只顾眼下，总能优先朝目标方向扩展。搜索失败返回 `None` → 退回局部 VFH。
- **局部层 VFH 方向扫描**【原文】：围绕机器人扫一圈候选方向，选"最朝目标、且前方够空"的那一个。最妙的设计是 `sign_first` 用 `player_id` 的**奇偶性**决定先往左还是先往右扫：两个机器人正对同一障碍冲过去时，若扫描顺序完全一样会同时往同一侧躲、结果在侧面又撞一起；用奇偶错开，一个偏左一个偏右，自然分流。
- **多层串联的优先级**【原文】：能直走就直走 → 要避障就先上全局 A\* → 全局搜不到才退回局部 VFH。全局规划成功后 `heading` 指向的是**路径上的下一个路点**而不是最终目标，这样才能真正绕开障碍。

## 二、代码与公式

**到达判定（原文"单元1"）**

```python
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

**障碍收集（原文"单元3"）**

```python
obstacles = collect_obstacles(
    self.context, self.id,
    ball=avoid_ball, robots=avoid_robots,
    goals=(avoid_ball or avoid_robots),
)
```

**全局 A\* 主循环（原文"单元3"，节选）**

```python
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

**局部 VFH 方向扫描（原文"单元3"）**

```python
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
```

**多层串联（原文"单元3"末）**

```python
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

**全部走位/避障参数（原文"单元4"表，值与本项目 `param.py` 一致）**

| 参数 | 默认值 | 控制什么 | 调整效果 |
|---|---|---|---|
| `ARRIVE_DIST` | 0.15 m | 到达阈值 | 调大→更早停（站位更松）；调小→贴得更紧 |
| `OMNI_DIST` | 1.0 m | 全向/转身切换距离 | 调大→更多"边走边转"（更灵活但可能晃）；调小→更早"先转身再走" |
| `TURN_THRESHOLD` | 0.5 rad | 先转身的角度门槛 | 调大→更敢斜着冲；调小→更爱先对齐再走 |
| `MAX_LINEAR` | 2.0 m/s | 最大线速度 | 调大→更快（可能刹不住/更晃） |
| `LINEAR_GAIN` | 1.5 | 平移 P 增益 | 调大→接近更快更"急"；调小→更柔 |
| `ANGULAR_GAIN` | 2.0 | 转向 P 增益 | 调大→转得更快更猛 |
| `PLAN_LOOKAHEAD` | 1.2 m | 局部探测射线长度 | 调大→提前发现障碍（更稳）；调小→反应更迟 |
| `PLAN_CLEARANCE` | 0.35 m | 局部最小安全余量 | 调大→离障碍更远（更保守）；调小→贴更近 |
| `PLAN_STEP` | 15° | 局部扫描步长 | 调小→方向更精细（路径更顺）；调大→更快但更糙 |
| `PLAN_MAX_OFFSET` | 100° | 局部最大偏转 | 调大→能绕更大弯；调小→更"认死理"直奔 |
| `USE_GLOBAL_PATH_PLANNER` | True | 是否启用全局 A\* | False→只用局部 VFH（更轻量但路径更差） |
| `GLOBAL_GRID_RESOLUTION_M` | 0.35 m | 栅格分辨率 | 调小→路径更平滑（更慢）；调大→更快更糙 |
| `GLOBAL_OBSTACLE_MARGIN_M` | 0.10 m | 障碍膨胀余量 | 调大→绕得更远（更安全） |
| `BALL_OBSTACLE_RADIUS` | 0.5 m | 球的障碍半径 | 调大→更不敢贴球（追球更难） |
| `OPPONENT_RADIUS` | 0.55 m | 对手机器人半径 | 调大→躲对手更远 |
| `TEAMMATE_RADIUS` | 0.48 m | 队友机器人半径 | 调大→队友间分得更开（防挤） |

**症状 → 参数对症表（原文"单元4"）**

| 现象 | 调整 | 原文补充 |
|---|---|---|
| 总是撞墙 / 撞门柱 | `PLAN_CLEARANCE → 0.5`，`GLOBAL_OBSTACLE_MARGIN_M → 0.15` | 确认 `walk_to` 时开启了 `avoid_robots` 或 `avoid_ball`（球门障碍依赖这两个开关之一） |
| 绕路绕得太远、太慢 | `GLOBAL_GRID_RESOLUTION_M → 0.25`，`PLAN_STEP → 10°`，`PLAN_MAX_OFFSET → 60°` | 前两项让路径更贴最优；最后一项限制乱拐幅度 |
| 两个机器人迎面卡住、互相顶 | `TEAMMATE_RADIUS → 0.55` | 先检查是否忘了用奇偶分流（框架已内置） |
| 到了点还不停、来回抖 | `ARRIVE_DIST → 0.2`，`LINEAR_GAIN → 1.2` | 前者增大到达判定距离，后者让减速更柔和 |

## 三、易错点与规则红线

- 【原文】`avoid_ball` / `avoid_robots` **默认关闭**，不显式打开就是走直线，会穿过球和队友。
- 【原文】`goals=(avoid_ball or avoid_robots)` 是"附带"的：只要开任一避障才建模球门障碍，两个都不开时撞门柱不会被规避。
- 【原文】全局 A\* 搜不到路返回 `None`，必须走局部 VFH 兜底；不能假设全局规划总成功。
- 【原文】全局规划成功后 `heading` 要指向**路径下一个路点**而不是终点，否则等于没绕。
- 【原文】`arrive_dist` 比的是直线距离而非路径长度，绕远路时可能"看似没到却判定到达"，属设计意图。
- 【原文】`sign_first` 的奇偶分流是**框架内置**的，自己另写避障时容易丢掉这个细节而互顶。
- 【经验建议】**`attack()` 的追球分支不带避障**（本项目 `src/player.py:591` 的 `walk_to` 没传 `avoid_robots`）。原文明确说"正常拼抢要直取球"，这在 1v1 合理；但 3v3 里两人同时追球会正面互顶。建议折中：追球时 `avoid_robots=True, avoid_ball=False`，既直取球又不撞队友。
- 【经验建议】**站位类动作应单独放大 `arrive_dist`**：`support()`/`guard()` 默认 0.15 m，球一直在动导致目标点一直变，会持续微调、原地抖。建议站位场景传 `arrive_dist=POSITION_ARRIVE_M=0.25`。
- 【经验建议】**性能红线**：本项目 `play()` 约 30 Hz、3 名球员每帧各调一次 `walk_to` → 全局 A\* 每秒最多 90 次（14 m/0.35 ≈ 40×26 ≈ 1000 格栅格）。AGENTS.md 要求 `play()` 不做重计算，建议按 `(player_id, 量化目标点)` 在 `store` 缓存路径 N 帧（如 6 帧），目标点变化超过 `PATH_CACHE_MOVE_TOL_M`（建议 0.5 m）才重算。**原文未讨论性能，此条为经验建议。**
- 【经验建议】`walk_to` 每次调用都会先 `release_kick()`（本项目 `src/player.py:387`），所以"边走边踢"不可能；`attack()` 在踢球态不再调 `walk_to` 是对的，自写技能时别在踢球态里穿插走位。

## 四、对本项目的具体改进建议

1. **`src/player.py:369` `walk_to` 增加路径缓存**：在函数开头按 `(self.id, round(tx/0.5), round(ty/0.5))` 查 `self._path_cache`（或 `store`），命中则直接用上次的 `planned_path` 与 `waypoint`，未命中才调 `plan_global_path`。这是 30 Hz × 3 人下最值得做的一处性能优化（原文未涉及，属工程补充）。
2. **`src/player.py:380-384` 的 docstring 已过期**：写着"避障(局部规划器,简化版 VFH)"，但函数体第 420 行实际是 `USE_GLOBAL_PATH_PLANNER` → `plan_global_path` → 失败才 `_plan_heading`。按原文"双层"结构改写注释，避免后续维护者误判。
3. **`src/player.py:566` `attack()` 的追球走位**：`self.walk_to(_behind_ball(...))` 改为 `self.walk_to(_behind_ball(...), avoid_robots=True, avoid_ball=False)`；同时保留"踢球态不避障直取"的现有结构。
4. **`src/player.py:595` `guard()` / `src/player.py:621` `support()` / `src/player.py:674` `move_to_position`**：三处都走 `walk_to`，统一加 `arrive_dist=POSITION_ARRIVE_M`，解决站位点持续微调抖动。
5. **`src/param.py:30` 之后新增**：`POSITION_ARRIVE_M = 0.25`（站位到达阈值）、`CHASE_ARRIVE_M = 0.2`（追球到达阈值）、`PATH_CACHE_MOVE_TOL_M = 0.5`、`PATH_CACHE_TTL_FRAMES = 6`。已有 16 个避障参数**不要动默认值**——原文给的值与 `param.py:116-129` 完全一致，说明这些是作者调过的基线。
6. **`src/param.py:101` `TEAMMATE_RADIUS = 0.48`**：若实测三人在禁区前沿互顶，按原文症状表提到 **0.55**；改完必须跑一场确认不会因为"队友半径太大"导致禁区里无路可走（A\* 会返回 `None` 而退回 VFH，表现为绕大圈）。
7. **`src/utils/path_planner.py`**：只在确认"撞门柱"复现时才按原文调 `GLOBAL_OBSTACLE_MARGIN_M` 0.10 → 0.15；`GLOBAL_FIELD_MARGIN_M = 0.25` 是场地边界外扩，**不要为了绕开对手把它调大**，否则贴边战术失效。

## 五、原文关键摘录

> 你可以把它理解成遥控器的"导航键"：你只说"去这个点"，它自己负责算出路线、避开障碍、判断到达。绝大多数战术里你都应该用 `walk_to`，把脑子留给"该去哪"而不是"怎么走过去"。

> 这段最妙的设计是 `sign_first` 用 `player_id` 的**奇偶性**决定先往左扫还是先往右扫。两个机器人正对同一个障碍冲过去时，如果它们扫描顺序完全一样，会同时往同一侧躲，结果在侧面又撞一起。

> `walk_to` 决策流程图：这张图的箭头代表**优先级**。能直走就直走；要避障就先上全局 A\*；全局搜不到才退回局部 VFH。

**A→B→C 三态（原文"单元2"）**

| 状态 | 条件 | 行为 |
|---|---|---|
| A | 距离目标较远，且方向不对 | 优先转向到朝向目标 → 变 B |
| B | 距离目标较远，但已面向目标 | 以常规步态走向目标 → 变 C |
| C | 距离较近，进入 `OMNI_DIST` 范围但未判定到达 | 切全向模式调整到目标位姿 |
