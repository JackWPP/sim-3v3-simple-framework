# 09 专题优化-定位球进攻
> 来源：https://booster.feishu.cn/wiki/GYriwP4YMiKeIrkyzCzc20pOnK3（原文约 1.0 万字）

## 一、战术剧本 / 核心要点

- **规则前提（G-03，全文最重要的一条）**【原文】：定位球开出后，开球方的进球不能靠一台机器人"一气呵成"，必须满足二者之一：① 进球前**至少 2 台机器人触球**；② 进球前的触球发生在**距开球位置 0.5 m 以外**。该规则适用于**所有定位球（含球门球、角球）**，且在球权开放（ball_free）之后**仍然有效**。→ 单人直接轰门是无效战术，传球接应不是"更优解"而是合规进球的硬性前提。
- **时间窗口**【原文】：规则给定位球发球队 **10 秒**发球时间，这 10 秒对方不能干扰，可让接应球员从容跑到战术位置再发球 —— 把死球时间当成"布阵窗口"就是定位球优势的来源。
- **现状 `_act_our_kickoff` 的三段式**【原文】：① 用 `store.prev_phase` 做阶段边沿检测，只在"刚进入开球阶段"或"原主罚者不可用"时重选，之后整个窗口沿用同一 id；② `attacker.kick(0.1, KICK_POWER_OUR_KICKOFF)` 朝 +x 略偏 0.1 rad 固定踢出；③ 其余两人一人 `guard()`、一人 `stop()`。
- **现状三个问题**【原文】：① 主罚永远朝固定方向（0.1 rad）踢，对手摸清规律后轻松拦截；② 另外两人只是"守 + 停"，没利用开球瞬间的人数优势做接应；③ 没有利用 10 秒窗口布阵。
- **开球三层升级**【原文】：
  - 第一层（布阵）：主罚者绕到球的后方站好；第二名球员在中场线后尽量靠前的位置，方便开球后迅速移动到接应点；第三人退到中圈偏后做保护。现状里第三人调 `stop()` 等于把 10 秒白白扔掉。
  - 第二层（瞄提前量）：不要瞄准队友**当前**位置，而瞄他**跑动路线上、球与他同时到达的那个点**。哪怕只把瞄准目标从"队友当前坐标"换成"接球点"，效果也立刻好一大截，形成推进配合。
  - 第三层（风格开关）：主罚者必须用 `store` 锁定（否则每帧重选会抖），这点现有代码已做对要保留；在此外加风格：**稳开** = 短距离推给近处队友，几乎不丢球权，代价是推进慢；**冒险直塞** = 大力斜塞对方半场空档，成功即单刀，失败立刻失球权，落后时或比赛快结束时搏一把。
- **两层状态机**【原文】：第一层 `get_phase` 把比赛压成 7 个互斥大局面（`NORMAL`/`OUR_KICKOFF`/`OPP_KICKOFF`/`OUR_SET_PLAY`/`OPP_SET_PLAY`/`READY`/`STOPPED`），只回答"这一刻该进攻、该避让、还是该站定"，管合法性；第二层 `get_set_play_type` 读 `set_play` 字段，只回答"是什么类型的定位球"，管战术效果。分层的三个理由：关注点分离、组合数从乘法变加法、支持渐进式迭代（今天只写 `CORNER_KICK`，其余继续 `_act_normal` 兜底也能跑）。
- **`get_set_play_type` 不区分是哪方主罚**【原文】，只确认类型；哪方由 `get_phase` 的 `OUR_SET_PLAY`/`OPP_SET_PLAY` 判定。
- **我方定位球按球种剧本**【原文】：

| 类型 | 原文给的进攻思路 |
|---|---|
| `THROW_IN` 界外球 | 就近短传，先保住球权 |
| `CORNER_KICK` 角球 | 往禁区送，找接应点抢第二落点 |
| `GOAL_KICK` 球门球 | 开向前场，组织推进 |
| `DIRECT_FREE_KICK` / `INDIRECT_FREE_KICK` / `PENALTY_KICK` | 原文未明确给出进攻剧本（本篇只给了防守侧的直接任意球人墙） |

- **角球五步剧本**【原文】（角球本质不是射门机会，而是一次可自由布置的传球机会，要回答三问：球踢到哪 / 谁去接 / 被断了怎么办）：
  1. **选主罚者** = 离球最近者，直接复用 `_select_closest_attacker`，快速发出的角球可能让对手措手不及。
  2. **选接应点**（整套战术的灵魂）= 对方禁区前沿、偏向一侧，示例 `(field.length/2 - 3.0, 1.5)`；不能选球门正前方（会被门将和后卫堆满），也不能太远（威胁不够）。这个坐标是最该反复调的参数。
  3. **踢向接应点而不是球门**：默认 `kick()` 走 `plan_kick()` 瞄对方门中心，角球必须用 `kick(方向, 力度)` 双参数形式，方向 = 从发球点到接应点。
  4. **接应者提前跑位**：从进入角球阶段那一刻起每帧 `walk_to(接应点)`，球发出时他应已站在接应点上。
  5. **第三人回防**：角球时两人压上、后场是空的，被解围打反击会瞬间丢球，第三人 `guard()`。
- **防抖闸门**【原文】：`if store.prev_phase != Phase.OUR_SET_PLAY or store.kickoff_taker is None:` 才重选主罚者与接应点。
- **用排除法找第三人**【原文】：`if p.id not in (store.kickoff_taker, store.receiver)`，这样即使有球员被罚下、场上只剩两人，代码也不会崩。
- **`store.support_target` 的作用**【原文】：主罚者瞄的点和接应者跑的点用同一个变量，保证两者一致。

## 二、代码与公式

**开球 v2（原文"单元2"参考代码，可直接抄结构）**

```python
def _act_our_kickoff_v2(context, players, store):
    active_ids = {p.id for p in players}
    if store.prev_phase != Phase.OUR_KICKOFF or store.kickoff_taker not in active_ids:
        store.kickoff_taker = _select_closest_attacker(context, players).id
        rest = [p for p in players if p.id != store.kickoff_taker]
        store.kickoff_runner = max(rest, key=lambda p: p.pose.x).id   # 前插者=剩下人里更靠前

    kicker = next(p for p in players if p.id == store.kickoff_taker)
    runner = next(p for p in players if p.id == store.kickoff_runner)

    g = context.game
    us = g.get_team_state(context.team_id)
    them = next((t for t in g.teams if t.team_number != context.team_id), None)
    diff = (us.score if us else 0) - (them.score if them else 0)
    if diff > 0:                                                  # 领先：稳开
        aim = (2.0, runner.pose.y)
        power = KICK_POWER_OUR_KICKOFF
    else:                                                         # 落后/平：直塞
        aim = (context.field.length / 2 - 4.0, runner.pose.y)
        power = KICK_POWER_MAX * 0.8

    runner.walk_to(aim, avoid_ball=True, avoid_robots=True)
    kicker.kick(angle_to(kicker.pose.x, kicker.pose.y, *aim), power)

    for p in players:
        if p.id not in (store.kickoff_taker, store.kickoff_runner):
            p.guard()
```

**角球（原文"单元4"参考代码，填入 `_act_our_set_play` 的 `CORNER_KICK` 分支）**

```python
def _act_our_corner(context, players, store):
    if store.prev_phase != Phase.OUR_SET_PLAY or store.kickoff_taker is None:
        store.kickoff_taker = _select_closest_attacker(context, players).id
        rest = [p for p in players if p.id != store.kickoff_taker]
        target = (context.field.length/2 - 3.0, 1.5)      # 对方禁区前点
        store.support_target = target
        store.receiver = min(rest, key=lambda p: dist(p.pose.x, p.pose.y, *target)).id

    kicker = next(p for p in players if p.id == store.kickoff_taker)
    receiver = next(p for p in players if p.id == store.receiver)

    aim = store.support_target
    kicker.kick(angle_to(kicker.pose.x, kicker.pose.y, *aim), KICK_POWER_OUR_KICKOFF)

    receiver.action = "corner_receive"
    receiver.walk_to(store.support_target, avoid_ball=True, avoid_robots=True)

    for p in players:
        if p.id not in (store.kickoff_taker, store.receiver):
            p.guard()
```

**`plan_kick()` 的三条公式（原文"单元5"）**

```python
kick_target   = opponent_goal(ctx)                     # (length/2 + GOAL_TARGET_DEPTH_M, 0)
kick_direction = angle_to(ball.x, ball.y, *kick_target) # 从【球】算，不是从机器人算
kick_power    = KICK_POWER_BACKFIELD if self._in_backfield() else KICK_POWER_DEFAULT
```

- `GOAL_TARGET_DEPTH_M`（`param.py`，默认 **0.25 m**）把目标点推到门线后方。原文解释：球极贴门线时若目标点正好在门线上，球与目标距离趋近 0，方向角会剧烈抖动甚至因浮点误差算反，导致机器人朝自家半场踢。原文建议"没有特殊理由不要动它"（调大如 0.5 方向更"扎实"但球在门侧时角度会偏）。
- 方向必须从**球**位算而非机器人位：球才是飞出去的物体，从机器人算只要没完美站在球正后方，击球瞬间就有明显角度偏差。
- `kick()` 内部夹取 `max(KICK_POWER_MIN, min(KICK_POWER_MAX, power))`，传多大都不会超过 `KICK_POWER_MAX`。

**四个力度参数（原文"单元5"表格）**

| 参数 | 谁在用 | 调它的意义 |
|---|---|---|
| `KICK_POWER_DEFAULT` | `plan_kick()`（前场） | 最常调的射门力度 |
| `KICK_POWER_BACKFIELD` | `plan_kick()`（后场） | 后场大脚解围可以更猛 |
| `KICK_POWER_OUR_KICKOFF` | 开球、角球（自己传） | 传球力度，通常小于射门 |
| `KICK_POWER_MIN` / `MAX` | `kick()` 内部夹取 | 安全护栏，超出会摔倒 |

**`kick_can_score()` 的直线外推公式（原文"单元5"末）**：给定踢球方向，`dx=cos(dir)`，若 `dx<=1e-6` 返回 False；`t=(goal_x-ball.x)/dx`，`y_at_goal = ball.y + sin(dir)*t`，判断 `|y_at_goal| <= goal_width/2`。用途：原文指出门将通常站在门中心，可改成"以门内偏向一边为射门目标"，用它在几个候选方向里筛能进的角度。

## 三、易错点与规则红线

- 【原文】**G-03 在 ball_free 之后仍然有效**。很多人以为"球被踢出去、球权开放了"就能直接补射，实际仍要满足 2 台触球或 0.5 m 外触球。
- 【原文】`get_set_play_type` 不区分主罚方。把"对方定位球"误判成"我方定位球"，球员会兴冲冲跑去碰球，然后被裁判罚下。
- 【原文】主罚者必须 `store` 锁定，否则每帧重选会导致三个人抢着开球、原地抖动。
- 【原文】接应者 `walk_to(..., avoid_ball=True)` 是必须的：球被踢出前误触会被判违规。
- 【原文】`plan_kick` 用球位算方向；若从机器人坐标计算，未完美站位时击球瞬间会产生角度偏差。
- 【原文】定位球只有 10 秒发球时间，接应者必须"提前跑"，等球飞过去才启动就晚了。
- 【经验建议】原文角球示例用 `angle_to(kicker.pose.x, kicker.pose.y, *aim)` 算方向，而 `plan_kick` 用球位算 —— 两者在机器人未贴球时有差（约 `CHASE_BEHIND_M`=0.35 m 量级）。传球建议统一用**球位**算方向，与 `plan_kick` 保持一致，误差更小。
- 【经验建议】原文"落后时、比赛快结束时用直塞"没给时间阈值；落地时应用 `context.game.secs_remaining` 判断（该字段本项目 `Context.game` 已有），不要用本地计时（属技术违规）。
- 【经验建议】`KICK_POWER_MAX * 0.8` 的直塞力度需实测：力度过大会让接应者追不上，10 秒窗口内反而丢球权。
- 【经验建议】角球接应点 `(length/2-3.0, 1.5)` 是"前点"示例；若对方门将习惯站近角，应改后点 `(length/2-3.0, -1.5)`，两个点都存进 `param.py` 便于切换。

## 四、对本项目的具体改进建议

1. **`src/main.py:303` `_act_our_set_play`（当前四个分支全调 `_act_normal`）**：拆成 `_act_our_corner` / `_act_our_throw_in` / `_act_our_goal_kick` / `_act_our_free_kick` 四个函数。**每个分支必须给全部球员分配动作**（主罚 + 接应 + 回防），只处理主罚者会让另外两人退化成 `_act_normal` 里的追球者，在定位球阶段等于送罚下。
2. **边沿检测必须按"球种"而非只按 phase**：`store.prev_phase` 在 `OUR_SET_PLAY` 内部不变，角球切成界外球时 `prev_phase` 仍是 `OUR_SET_PLAY`，角色不会重选。应新增 `store.set_play_kind`，与 `get_set_play_type(context)` 比较，类型变化即重选主罚者/接应点。
3. **`src/main.py:115` `init_store`**：新增并初始化 `store.set_play_kind = None`、`store.set_play_taker = None`、`store.set_play_receiver = None`、`store.set_play_target = None`。**不要复用 `store.kickoff_taker`**（原文示例复用了，但本项目 `_act_our_kickoff` 在 `src/main.py:263` 用它做开球锁，复用会互相覆盖）。
4. **`src/main.py:257` `_act_our_kickoff`**：加 `store.kickoff_runner`（`max(rest, key=lambda p: p.pose.x)`），把固定的 `attacker.kick(0.1, KICK_POWER_OUR_KICKOFF)`（`src/main.py:273`）换成按接应点算方向；第三人从 `p.stop()` 改成退到中圈偏后保护位。注意本项目 `skills`/规则要求开球机器人在球离开开球点 0.5 m 内不得射门，`kick` 方向应指向队友而非球门。
5. **`src/param.py:23` 力度没有区分**：现有 `KICK_POWER_DEFAULT = 5.0`、`KICK_POWER_BACKFIELD = 5.0`、`KICK_POWER_OUR_KICKOFF = 5.0` 三个值全相同，等于没分场景。建议新增 `KICK_POWER_SET_PLAY_PASS = 3.5`（定位球短传）、`KICK_POWER_SET_PLAY_THROUGH = KICK_POWER_MAX * 0.8`（直塞）、`KICK_POWER_GOAL_KICK = 7.0`（球门球开向前场）。
6. **`src/param.py` 新增具名常量**：`CORNER_RECEIVE_X_M = 3.0`（接应点距对方门线内缩量，坐标 = `length/2 - CORNER_RECEIVE_X_M`）、`CORNER_RECEIVE_Y_NEAR_M = 1.5`、`CORNER_RECEIVE_Y_FAR_M = -1.5`、`THROW_IN_PASS_DIST_M`、`GOAL_KICK_TARGET_X_M`、`SET_PLAY_TAKER_HYST_M`（换主罚者的距离余量，避免抖动）、`KICKOFF_RUNNER_AHEAD_M`（前插者站位提前量）。
7. **`src/player.py` 新增 `pass_to(self, target: tuple[float, float], power: float)`**：内部 `kick(angle_to(ball.x, ball.y, *target), power)`，并前置判空 `self.pose`/`context.ball`。让四个定位球分支都调它，避免每处重复算方向、也统一"用球位算"的口径。
8. **`src/player.py:232` `plan_kick` 射门瞄边**：在 `opponent_goal` 两侧各取一个候选方向（门内偏 ±`goal_width/2*0.6`），用现有 `kick_can_score`（`src/player.py:302`）筛出能进的，选离对方门将更远的一侧。原文只给了 `kick_can_score` 工具，**具体选点算法原文未明确**，此处属自拟实现。

## 五、原文关键摘录

> **规则前提（G-03）：** 定位球开出后，开球方的进球不能靠一台机器人"一气呵成"，必须满足两个条件之一：① 进球前至少有 2 台机器人触球；② 进球前的触球发生在距开球位置 0.5 m 以外。该规则适用于**所有定位球（包括球门球、角球）**，并且在球权开放（ball_free）之后仍然有效。

> 规则给了定位球发球队 10 秒钟发球时间。这 10 秒里，对方不能干扰……把死球时间变成你的"布阵窗口"就是定位球优势的来源。

| 返回值 | 含义 | 进攻思路一句话 |
|---|---|---|
| `CORNER_KICK` | 角球 | 往禁区送，找接应点抢第二落点 |
| `GOAL_KICK` | 球门球 | 开向前场，组织推进 |
| `THROW_IN` | 界外球 | 就近短传，先保住球权 |

**角球五步清单（原文"单元4"）**：① 选主罚者（最近）→ ② 选接应点（禁区前沿偏一侧）→ ③ 踢向接应点而非球门 → ④ 接应者提前跑位 → ⑤ 第三人回防。

> 角球的本质不是射门机会，而是一次可以自由布置的传球机会。
