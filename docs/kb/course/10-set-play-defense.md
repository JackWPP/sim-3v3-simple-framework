# 10 专题优化-定位球防守
> 来源：https://booster.feishu.cn/wiki/LPxEw6NsKiEHyekS7K4czYOon0g（原文约 6600 字）

## 一、战术剧本 / 核心要点

- **防守哲学**【原文】：用空间换时间、用结构换机会。你不必第一时间把球抢下来，只要延缓对手推进速度，己方阵型就有时间重新集结；全队站位形成的那张"网"本身就是武器，对手在网里越久失误概率越高，失误那一刻就是反击机会。→ 防守时 `walk_to` 有时比 `attack` 更重要。
- **五条防守原则**【原文】：
  1. **压缩空间**：球员之间保持很小的纵向、横向距离。三个人站成边长 **3 米**的三角形，和站成一条散开 **8 米**的直线，覆盖能力天差地别。代码里对应 `SUPPORT_DIST_M`（`param.py`，默认 **3.0**）：值越小阵型越紧凑、越不容易被中路直塞打穿，代价是反击时离对方球门更远。
  2. **区域联防**：每人守一块区域而不是死盯一个人，阵型不易被拉散，缺点是区域交界处可能出现空档（对应"分区策略"篇）。
  3. **人墙**：在任意球射门路线上排人，缩小门将需要扑救的角度，本质是阻挡最危险的球路。
  4. **包夹**：两人对持球者前后夹击，一人堵传球路线、一人逼抢，迫使他仓促出球。代码上读 `context.opponents` 找出离球最近的对手，派球员贴身干扰。
  5. **由守转攻**：抢断成功那一瞬是全场最好的反击窗口（对手刚压上、阵型是散的），球权到手就要立刻安排前插跑位。
- **对方中场开球（`OPP_KICKOFF`）现状剧本**【原文】：① 选离己方球门最近的人 `guard()`（他跑回门线成本最低）；② 用 `context.field.circle_radius` 读出中圈半径，往外推 **0.5 m** 和 **2.0 m** 得到两个退守点 `(-r-0.5, 0.0)`、`(-r-2.0, 0.5)`；③ 两人 `walk_to` 一律带 `avoid_ball=True`、`avoid_robots=True`。
- **该剧本的缺点**【原文】：点位写死，不管球往哪边发展两人都站同样位置，缺少变化、容易被针对。
- **对方远距离发球时全队三件事**【原文】：① **堵住最短的那条线**——球最终必须经过"球 → 我方球门"连线，`support()` 正是把球员放在这条线上距球 `SUPPORT_DIST_M` 处；② **分层，不要挤在一起**——三人站成前中后三层（第一落点、第二落点、门线），对手突破第一层还有第二层；③ **只占位不触球**——`OPP_KICKOFF`/`OPP_SET_PLAY` 阶段触球即违规，所有走位必须 `avoid_ball=True`。
- **对方开球直接大脚攻门**【原文】：三人在球的路线上创造最大阻挡面积；防吊门要考虑落点；远射必然沿"球 → 我方球门"这条线飞，所以封堵者不是随便站门前而是站**射门线上**；多人封堵时加**水平偏置**以覆盖更大横向宽度；同时留一名门将在门线做最后保险，避免身后完全空门。
- **对方定位球按类型防守**【原文】：

| 对方定位球 | 原文建议防守 |
|---|---|
| `CORNER_KICK` 角球 | 禁区内密集站位，门将出击或守点；派一人守**近门柱**、一人守**小禁区线** |
| `THROW_IN` 界外球 | 就近压迫持球人 + 区域回收 |
| `GOAL_KICK` 对方球门球 | 原文写"见下方'对方球门球策略'"，但全文**没有该小节**，具体打法**原文未明确** |
| `DIRECT_FREE_KICK` 直接任意球 | 两人排人墙、一人守门（下节四步） |

- **人墙战术（两人排墙、一人守门）**【原文】：
  - **优势**：① 简化门将扑救任务——人墙挡住近角一侧，门将只需守另一侧，把"左边还是右边"变成"只能是右边"；② 逼迫对手选更难的进攻方式（吊射精度难控，或改为传球，从"射门威胁"降级成"运动战"）；③ 占位不触球，零违规风险。
  - **代价**：① 可能被绕过——人墙只覆盖射门线正中间时，对手可往空档踢，机器人还得花时间转身；② 可能被吊射——**机器人不会跳，人墙高度固定**，吊射是天然克星；③ 两个人被"锁死"，整段定位球期间只剩门将一个机动兵力，对手改短传则人墙白排。
  - **人数按距离决定**【原文】：职业球队会根据距离决定"排几个人"，**距离远就少排甚至不排**。
- **人墙四步构建**【原文】：
  1. 计算射门路线：`angle_to(ball.x, ball.y, *own_goal(context))`，这条线是整套战术的坐标轴。
  2. 分配门将：`min(players, key=离己方门距离)`，让最近的人回去守门，到位最快。
  3. 人墙站位：沿射门线从球前进 `OPP_SET_WALL_DIST_M`（默认 **2.0 m**）得墙中心，两名球员分别往两侧各偏 **0.3 m**，形成有宽度的墙。
  4. 所有走位避球：人墙离球近最易误触，路径规划必须把球当障碍物绕开。
- **盯人防守练习剧本（1 盯人 + 1 回收 + 1 守门）**【原文】：① 从 `context.opponents.values()` 用 `min` **排除离球最近的发球队员**，选出另一个等待接球的接应队员；② 在我方球员里选离该接应队员最近的人去盯；③ 盯防站位**不要**移动到接应队员坐标（会撞上，倒的可能是自己），而站在**接应队员与球的连线上**、距接应队员较近的位置；④ 其余两人：一人 `guard()`，一人 `support()` 或走中路做区域防守补空当；⑤ 全部 `avoid_ball=True`。

## 二、代码与公式

**`_act_opp_kickoff` 现状（原文"单元2"节选，与本项目 `src/main.py:287` 一致）**

```python
guard = min(players, key=...离己方门最近...)
guard.guard()

rest = [p for p in players if p is not guard]
r = context.field.circle_radius                 # 中圈半径 1.5m
slots = [(-r - 0.5, 0.0), (-r - 2.0, 0.5)]     # 其余两人退到中圈外固定点
for p, target in zip(rest, slots):
    p.walk_to(target, avoid_ball=True, avoid_robots=True)
```

**"两人人墙 + 一人守门"（原文"单元4"参考代码，填 `_act_opp_set_play` 的 `DIRECT_FREE_KICK` 分支）**

```python
def _act_opp_free_kick(context, players, store):
    ball = context.ball
    if ball is None:
        for p in players: p.stop()
        return

    # 第一步：射门线 = 球 → 我方球门中心
    gx, gy = own_goal(context)
    shot_dir = angle_to(ball.x, ball.y, gx, gy)

    # 第二步：门将 = 离己方门最近者
    keeper = min(players, key=lambda p: dist(p.pose.x, p.pose.y, gx, gy))
    keeper.guard()

    # 第三步：其余两人在射门线上、距球 OPP_SET_WALL_DIST_M(2.0m) 处排人墙
    wall_players = [p for p in players if p is not keeper]
    for i, p in enumerate(wall_players):
        wx = ball.x + math.cos(shot_dir) * OPP_SET_WALL_DIST_M
        wy = ball.y + math.sin(shot_dir) * OPP_SET_WALL_DIST_M + (i - 0.5) * 0.6
        p.action = "wall"
        # 第四步：只占位，绝不触球
        p.walk_to((wx, wy), avoid_ball=True, avoid_robots=True)
```

**关键公式与参数**

- 人墙点：`(bx + cos(shot_dir)*D, by + sin(shot_dir)*D + (i-0.5)*0.6)`，`D = OPP_SET_WALL_DIST_M`；两人时 `i=0,1` → 横向偏 **-0.3 m / +0.3 m**（总宽 0.6 m）。
- `shot_dir = angle_to(ball.x, ball.y, gx, gy)`，即"球 → 己方门中心"，这是所有封堵位置的坐标轴。
- `OPP_SET_WALL_DIST_M`（`param.py`，默认 **2.0 m**）：**太近可能违规、太远失去意义**；原文说 2.0 m 只是"经验起点"，要用自己的比赛数据校准。
- 中圈退守点：`(-r-0.5, 0.0)` 与 `(-r-2.0, 0.5)`，`r = context.field.circle_radius` = **1.5 m**（本方 `FieldDimensions` 实测值）→ 实际坐标 `(-2.0, 0.0)`、`(-3.5, 0.5)`。
- 支撑点：`support()` 放在球与己方门中心连线上、距球 `SUPPORT_DIST_M` = **3.0 m** 处。

## 三、易错点与规则红线

- 【原文】**`_act_opp_set_play` 现在直接调 `_act_normal` 是一个大坑**：`_act_normal` 第一件事就是挑一个 `attacker` 去 `attack()`，在对方定位球阶段这等于主动送上门去被罚下。
- 【原文】`OPP_KICKOFF` / `OPP_SET_PLAY` 阶段**触球即违规**；所有走位带 `avoid_ball=True`，宁可绕路也绝不碰球。
- 【原文】人墙两人在整个定位球期间几乎不做别的事，等于只剩门将一个机动兵力；对手改短传则人墙白排。
- 【原文】机器人不会跳，人墙的"高度"是固定的，**吊射是人墙的天然克星**。
- 【原文】盯人时站到接应队员的坐标会撞上，"倒的可能是自己"；必须站连线而不是站身上。
- 【原文】对方球门球（`GOAL_KICK`）的防守打法在原文中**只给了引用、没有正文**——属原文未明确，不要凭空补。
- 【经验建议】本项目 `Player.guard()`（`src/player.py:595`）把所有人送到同一个 `own_goal_area_center`，两人同时 `guard()` 会互相挤踏（`avoid_robots=True` 只能绕行、不能消除目标重合）。多人防守时**必须给同一点加横向偏置**，例如 ±0.6 m。这条是原文没写、本项目实测会踩的坑。
- 【经验建议】人墙距离要做钳制：若球离门很近（`dist(ball, own_goal) < 2*OPP_SET_WALL_DIST_M`），按 2.0 m 沿射门线推会把人推到门线后方。建议 `D = min(OPP_SET_WALL_DIST_M, 0.5*dist_ball_to_goal)`，并把结果 `clamp_inside_field`。
- 【经验建议】本项目规则要求对方定位球期间所有机器人距球 **> 1.45 m**（留余量）。2.0 m 的人墙距离有余量，但人墙的**横向偏置**会让某一端更靠近球，需按 `hypot(D, 0.3)` ≈ 2.02 m 复核仍大于阈值。
- 【经验建议】原文"距离远就少排甚至不排"没给距离阈值；落地时用 `dist(ball, own_goal)` 与 `penalty_area_length`（本项目 3.0 m）、场地半长（7.0 m）做分段判断。

## 四、对本项目的具体改进建议

1. **`src/main.py:318` `_act_opp_set_play`（当前一行 `_act_normal(...)`）——最高优先级**：这是会把球员送罚下的写法。改成按 `get_set_play_type(context)` 分派到 `_act_opp_free_kick` / `_act_opp_corner` / `_act_opp_throw_in` / `_act_opp_goal_kick`，**每个分支给全部球员分配动作**，且分支内绝不调用 `attack()`、绝不调 `kick()`。
2. **`src/main.py:287` `_act_opp_kickoff`**：`slots` 写死为 `[(-r-0.5, 0.0), (-r-2.0, 0.5)]`。改成动态：以"球 → 己方门"连线为轴，两个退守点分别落在轴上距球 `OPP_KICKOFF_BLOCK_DIST_M` 和再远 `OPP_KICKOFF_BLOCK_GAP_M` 处，并按 `ball.y` 的正负镜像横偏（球在 y>0 时退守点向 -y 侧偏），最后 `clamp_inside_field` 并保证到场地中心距离 > `circle_radius + CIRCLE_MARGIN_M`（本项目已有该常量）。
3. **`src/main.py` 新增 `_act_opp_free_kick(context, players, store)`**：照抄原文四步，但把 `p.walk_to` 换成本项目已有的 `p.move_to_position(...)`（它内部已 `avoid_ball=True, avoid_robots=True` 并面向球），减少手写参数出错。
4. **`src/player.py:595` `guard()` 增加 `lateral: float = 0.0` 参数**：`home = (own_goal_area_center.x, own_goal_area_center.y + lateral)`，多人守门时传 ±0.6。这是原文没覆盖、但本项目 3 人制里几乎必然遇到的挤踏问题。
5. **`src/player.py` 新增 `wall(target)` 与 `mark(target_opponent_pose)` 两个方法**：`wall` 只做 `walk_to(target, face=angle_to(self→ball), avoid_ball=True, avoid_robots=True)`；`mark` 计算"接应者与球连线、距接应者 `OPP_MARK_DIST_M`"的点再走位。二者都复用 `move_to_position` 的钳制逻辑。
6. **`src/param.py` 扩充（`OPP_SET_WALL_DIST_M = 2.0` 已在第 78 行，保留）**：新增 `OPP_SET_WALL_LATERAL_M = 0.3`（单人横偏）、`OPP_SET_WALL_MAX_FRACTION = 0.5`（人墙距离占球门距离比例上限）、`OPP_SET_WALL_MIN_GOAL_DIST_M`（超过此距离才排 2 人墙，否则 1 人墙）、`OPP_CORNER_NEAR_POST_M`（近门柱站位距门柱距离）、`OPP_CORNER_BOX_LINE_M`（小禁区线站位）、`OPP_MARK_DIST_M`（盯人贴身距离，建议 0.8~1.0）、`OPP_PRESS_DIST_M`（界外球就近压迫距离）、`OPP_KICKOFF_BLOCK_DIST_M`、`OPP_KICKOFF_BLOCK_GAP_M`。
7. **人数自适应**：在 `_act_opp_free_kick` 里先算 `d = dist(ball.x, ball.y, *own_goal(context))`；`d > OPP_SET_WALL_MIN_GOAL_DIST_M` 时排 2 人墙，否则只排 1 人墙、另一人做区域回收——直接落实原文"距离远就少排甚至不排"。

## 五、原文关键摘录

> 防守的核心哲学可以概括为一句话：用空间换时间、用结构换机会。

> 进攻代码关心的是怎么移动球，防守代码关心的是"站在哪里，让对手最难受"。

| 维度 | 原文列出的三条 |
|---|---|
| 人墙优势 | ① 简化门将扑救任务（把"左边还是右边"变成"只能是右边"）② 逼迫对手选更难的进攻方式（吊射精度难控 / 改为传球降级为运动战）③ 占位不触球，零违规风险 |
| 人墙代价 | ① 可能被绕过（只覆盖射门线正中间时对手打空档，机器人还要转身）② 可能被吊射（机器人不会跳）③ 两个人被锁死，只剩门将一个机动兵力 |

**人墙四步（原文"单元4"）**：① 算射门线 `angle_to(ball → own_goal)` → ② 最近者当门将 `guard()` → ③ 沿射门线距球 2.0 m、两人各偏 0.3 m → ④ 所有走位 `avoid_ball=True`。

**盯人练习五步（原文"章节练习"）**：① 从 `context.opponents` 排除发球者选接应者 → ② 选离接应者最近的队友 → ③ 站"接应者—球"连线上而非接应者坐标 → ④ 一人 `guard()`、一人 `support()` 补位 → ⑤ 全部 `avoid_ball=True`。
