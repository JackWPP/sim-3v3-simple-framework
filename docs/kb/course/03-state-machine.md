# 03 深入理解状态机
> 来源：https://booster.feishu.cn/wiki/Yc3lwJrHziXvm4kbIiWc84Panng（原文约 12.9k 字）

## 一、核心要点

- 状态机解决策略最关键的问题：**"此刻是什么局面，我该用哪套打法？"**；答错这一步，"再漂亮的进攻套路也会用错时机，甚至被判违规"。
- 本项目用 `Phase` 枚举当红绿灯，共 **7 种**：`NORMAL`、`OUR_KICKOFF`、`OPP_KICKOFF`、`OUR_SET_PLAY`、`OPP_SET_PLAY`、`READY`、`STOPPED`。
- 命名成对（`OUR_`/`OPP_`）的原因：**同一类死球，主罚方与防守方动作完全相反，必须分开处理**。
- 用 `Enum` 而非字符串/整数常量的三个好处：**① 写错立即报错；② IDE 自动补全；③ 打印友好**。
- `get_phase(context)` 只读 `context.game`（裁判机数据），**每层判断一旦成立就立刻 `return`，"代码的物理顺序就是逻辑的优先级顺序"**，没有深层 `else` 嵌套。
- 优先级从"最不该动"到"可以自由发挥"分三层：
  1. **先排除非比赛状态**（`game is None` → `STOPPED`；`READY` → `READY`；`SET`/`INITIAL`/`FINISHED`/`stopped` → `STOPPED`）；
  2. **再分辨该谁发球**：`set_play != NONE` 且 `kicking_team != KICKING_TEAM_NONE` → 定位球；`secondary_time > 0` 且 `kicking_team != KICKING_TEAM_NONE` → 开球；按 `kicking_team == our_team` 分 `OUR_`/`OPP_`；
  3. **最后 `NORMAL` 兜底**：只有"不是暂停、不是走位、不是定位球、不是开球"四件事全成立才轮到它。
- `secondary_time` 的语义：**开球（kick-off）短暂的"允许触球"窗口，`secondary_time > 0` 表示窗口存在**；`get_phase` 靠它区分"正在开球"与"开球完毕进入 NORMAL"，**窗口一过立刻回到 `NORMAL`**——所以开球逻辑必须"赶在窗口内把球踢出去"。
- **`play()` 是静态方法，每帧重新调用，局部变量不保留；只有 `store` 里的数据能跨帧存活——"这也是本项目里'记忆'的唯一正确落点"**。
- 相位边沿检测：`store.prev_phase = store.cur_phase; store.cur_phase = phase` 构成滑动窗口；`if store.cur_phase != store.prev_phase:` 成立即"这一帧刚切进来"。**只做一次的动作必须挂在边沿上**，否则球员会在两人之间来回横跳（`_act_our_kickoff` 的 `store.kickoff_taker` 就靠此机制维持稳定）。
- "活性自理"放在分派**之前**，逐条规则：
  - `p.ensure_ready()`：摔倒就起身、没在 `walk` 模式就切模式，**对所有人都做，包括被罚下的**——"这样罚时一到，他解禁那一帧就已经站好了"；
  - `is_penalized` → 只能起身/切模式，**不能移动**，直接 `stop()`；
  - 还没就绪（正在爬起/切模式）→ 这帧别指望他；
  - `pose is None` → 不参与分派，"它连自己在哪都不知道，让它跑就是乱跑"；
  - 只有"健康且已知位置"的球员进入 `active`。
- 分派链只做转交、不做战术判断，**保证每帧有且只有一个 `_act_*` 被执行**，杜绝"两个函数同时指挥同一个机器人"。
- `NORMAL` 之外的每个分支先调 `_clear_normal_sticky(store)` 清空 `store.normal_attacker`，避免死球结束回 `NORMAL` 时沿用旧决定。
- `_act_normal` 用**逐层剥离**分派角色，不管场上 3 人、2 人还是 1 人都正确工作；选 attacker 时传入 `store.normal_attacker` 做**迟滞**（`ATTACKER_KEEP_DIST_MARGIN_M`）。
- 角色（`role`）独立于球员（`player id`）的三点好处：**① 动态分工**（这帧 attacker、下帧可能 guard）；**② 战术与职责解耦**（只想"需要一个进攻者"，不必管几号）；**③ 便于做复杂阵型**。
- 原文的"留白"结论：**高分队伍的状态机并没定义更多状态，而是将状态内部的逻辑分得更细**；三类典型优化（都不新增顶层 Phase，只在 `NORMAL` 内部再判断）：
  1. **落后压上、领先收缩**（读比分：落后时把 `guard` 推到中场当第二进攻点；领先时让 `support` 回撤成第二后卫）；
  2. **终场前死守/搏命**（结合 `secs_remaining`：剩十几秒且 1 球领先 → 全员回收禁区、往边路和前场大脚解围；落后 → 连门将都压上）；
  3. **按球的位置细分打法**（球在对方禁区 → 全线压上；中场 → 标准站位；自家禁区 → 全员回收、优先解围）。
- 分层原则（原文结论）：**"外部规则决定的东西放顶层，你自己的战术偏好放内层"**。把"落后"做成并列 Phase 会与 `OPP_SET_PLAY` 冲突——"两个都想要，可状态机只能选一个"。

## 二、代码与公式

### 2.1 `Phase` 枚举（原文 单元2，`src/main.py`）

```python
class Phase(Enum):
    NORMAL = "normal"              # 正常拼抢（比赛的主体时间，双方自由争抢）
    OUR_KICKOFF = "our_kickoff"    # 我方开中场球（中圈开球，由我方先触球）
    OPP_KICKOFF = "opp_kickoff"    # 对方开中场球（我方须退守、不能干扰）
    OUR_SET_PLAY = "our_set_play"  # 我方定位球（任意球/角球/点球/球门球，我方主罚）
    OPP_SET_PLAY = "opp_set_play"  # 对方定位球（我方须避让、布防）
    READY = "ready"                # 走位状态（开赛前、进球后、半场等，须回到指定站位）
    STOPPED = "stopped"            # 暂停/未开始/结束（SET/INITIAL/FINISHED/无裁判数据）
```

### 2.2 `get_phase`（原文 单元3，与 `src/main.py:48-82` 一致）

```python
def get_phase(context: Context) -> Phase:
    g = context.game
    if g is None:
        return Phase.STOPPED                       # ① 没裁判数据 → 停
    state = g.state
    if state == GameState.READY:
        return Phase.READY                         # ② READY 走位
    if state == GameState.PLAYING and not g.stopped:
        if g.set_play != SetPlay.NONE and g.kicking_team != KICKING_TEAM_NONE:
            return Phase.OUR_SET_PLAY if g.kicking_team == our_team else Phase.OPP_SET_PLAY   # ③
        if g.secondary_time > 0 and g.kicking_team != KICKING_TEAM_NONE:
            return Phase.OUR_KICKOFF if g.kicking_team == our_team else Phase.OPP_KICKOFF      # ④
        return Phase.NORMAL                        # ⑤
    return Phase.STOPPED                           # ⑥ SET/INITIAL/FINISHED
```

### 2.3 相位边沿（原文 单元4）

```python
phase = get_phase(context)
store.prev_phase = store.cur_phase     # 滑动窗口：新值推进，旧值入 prev
store.cur_phase = phase
# 只执行一次的动作用这个条件
if store.cur_phase != store.prev_phase:
    ...
```

### 2.4 分派链（原文 单元4，与 `src/main.py:162-183` 一致）

```python
if phase == Phase.NORMAL:
    _act_normal(context, active, store)
elif phase == Phase.OUR_KICKOFF:
    _clear_normal_sticky(store); _act_our_kickoff(context, active, store)
elif phase == Phase.OPP_KICKOFF:
    _clear_normal_sticky(store); _act_opp_kickoff(context, active)
elif phase == Phase.OUR_SET_PLAY:
    _clear_normal_sticky(store); _act_our_set_play(context, active, store)
elif phase == Phase.OPP_SET_PLAY:
    _clear_normal_sticky(store); _act_opp_set_play(context, active, store)
elif phase == Phase.READY:
    _clear_normal_sticky(store); _act_ready(context, active)
elif phase == Phase.STOPPED:
    _clear_normal_sticky(store)
    for p in active:
        p.action = "stopped"; p.stop()
```

### 2.5 `_act_normal` 三角色（原文 单元5）

```python
def _act_normal(context, players, store):
    attacker = _select_closest_attacker(context, players, store.normal_attacker)
    store.normal_attacker = attacker.id
    attacker.attack()                              # ① 离球最近 → 进攻

    rest = [p for p in players if p is not attacker]
    if rest:
        gx, gy = own_goal(context)
        guard = min(rest, key=lambda p: dist(p.pose.x, p.pose.y, gx, gy))
        guard.guard()                              # ② 剩下里离己方门最近 → 守门
        rest = [p for p in rest if p is not guard]

    for p in rest:
        p.support()                                # ③ 其余 → 支援
```

### 2.6 落后压上（原文 单元6，"可直接粘贴使用"）

```python
def is_losing(context) -> bool:
    """我方比分是否落后。读不到裁判机比分时保守返回 False。"""
    game = context.game
    if game is None or not getattr(game, "teams", None):
        return False
    my_score = next((t.score for t in game.teams if t.team_id == context.team_id), 0)
    opp_score = next((t.score for t in game.teams if t.team_id != context.team_id), 0)
    return my_score < opp_score


def _act_all_out_attack(context, players, store) -> None:
    """落后时的全员压上：所有可行动球员一起抢球射门，不留守门员。"""
    for p in players:
        p.attack()
```

接入点（原文）：`if phase == Phase.NORMAL:` 内先 `if is_losing(context): _act_all_out_attack(...)` 否则 `_act_normal(...)`，**其它分支一个字都不用改**。

### 2.7 优先级的走查示例（原文，对方角球）

`state=PLAYING` → 跳过 ①；不是 `READY` → 跳过 ②；`set_play == CORNER_KICK` 且 `kicking_team` 是对方 → 立刻返回 `Phase.OPP_SET_PLAY`，④⑤ 根本不执行 → `_act_opp_set_play`：一人回门前守近角，其余站到规则距离外堵传中路线，**没有任何人冲上去抢球**。

## 三、易错点

- 【原文】**角色分派前不筛 `active`**。被罚下者"还站在场上、坐标也是有效的"，纯数学上可能是"离球最近的那个"；被选成 `attacker` 后 `attack()` 立即生效 → 再次犯规、刷新罚站时间，且全队无人抢球。原文评价：**"这个 bug 不会报错、不会崩溃，只会让你输球，是最难排查的那一类。"**
- 【原文】**把"战术倾向"做成并列 Phase**（如 `Phase.LOSING`）。对方任意球时我方也落后 → 状态机只能选一个，逻辑冲突；应放进 `NORMAL` 内部。
- 【原文】**新手一上来定义大量状态**："结果一半从不被触发，反而把自己绕晕"。建议先熟悉 7 个基本 Phase，现有不够用再加。
- 【原文】**每帧重选主罚者**：不挂在边沿上，球员会在两人之间来回横跳、谁也没真去踢球。
- 【原文】**活性自理若放到分派之后**：`None` 位姿球员被 `attack()` 时可能在内部解引用 `pose.x` 崩溃；更隐蔽的是"被罚下者恰好离球最近被选成 attacker，这一帧没有任何人真的去抢球"。
- 【原文】**漏判 `kicking_team == KICKING_TEAM_NONE`（255）**：`set_play`/`secondary_time` 有值但无人主罚时，若只判断 `set_play != NONE` 就会误判成 `OUR_SET_PLAY`（`kicking_team == 255 != our_team` → 走 `OPP_SET_PLAY`，或反过来）。原代码两个条件都用 `and` 连着，不要拆。
- 【原文骨架 vs 本项目现状】**原文 `_act_normal` 片段没有 `attacker.action` / `guard.action` 赋值**，当前 `src/main.py:240`、`src/main.py:253` 有；**原文还直接用 `store.normal_attacker`**，当前实现用 `getattr(store, "normal_attacker", None)`（`src/main.py:237`），因为 `init_store` 之外可能没有该属性。
- 【原文代码 vs 本项目类型】**`is_losing` 里 `t.team_id` 在本项目不存在**：`TeamState` 的字段是 **`team_number`**（`src/framework/types.py`），`context.team_id` 是 `Context` 的字段。照抄会 `AttributeError`。正确写法见第四节。
- 【原文代码 vs 本项目类型】`game.teams` 是 `tuple[TeamState, ...]`，默认就有两队；`getattr(game, "teams", None)` 这段保护在 dataclass 下恒为真，真正需要保护的是 `game is None`。
- 【原文】**忽略 `g.stopped`**：`PLAYING` 也可能被裁判暂停（`stopped=True`），此时必须走 `STOPPED` 而不是 `NORMAL`，否则 SET 期间乱动会被罚。

## 四、对本项目的具体改进建议

1. **`src/main.py:_act_our_set_play`（当前 `src/main.py:303-315` 是 3 个 `if` 分支 + 兜底，共 4 处全部直接回落 `_act_normal`）**：按 `get_set_play_type(context)` 真正分支，每支路给**所有**球员分配动作：
   - `THROW_IN`：先定出球方向 `d = angle_to(ball, target)`，主罚者 `p.walk_to((ball.x - 0.35*cos(d), ball.y - 0.35*sin(d)), avoid_ball=False)` 绕到球后 0.35 m，到达后再 `p.kick(d, KICK_POWER_DEFAULT)`；另两人跑到球前方 1.5 m、2.5 m 接应（**不能**用 `move_to_position((ball.x - 0.3, ball.y))` 这种"固定往 -x 退 0.3 m"的写法，界外球的出球方向通常不是 -x）；
   - `GOAL_KICK`：门将/后卫第一脚**不朝己方门**——`player.py:kick_can_score(dir)`（`src/player.py:302-326`）只回答"这个方向直线踢能否进**对方**球门"，**不能**用来做反向判断；应显式约束出球方向 `math.cos(d) > 0`（朝 +x 半场），目标点取 `(ball.x + 2.0, ±(field.width/2 - 1.0))` 的边路空当，再 `kick(d, KICK_POWER_DEFAULT)`；
   - `CORNER_KICK`：主罚者踢向近门柱前 0.5 m，另一人抢前点；
   - 其余（`DIRECT_FREE_KICK`/`INDIRECT_FREE_KICK`/`PENALTY_KICK`/`NONE`）才回落 `_act_normal`。
2. **`src/main.py:_act_opp_set_play`（当前 `src/main.py:318-320` 直接 `_act_normal`）**：这是规则风险最高的一处——`_act_normal` 会让最近者 `attack()` 冲球。改为：门将 `guard()`；其余人 `walk_to` 到距球 `OPPONENT_RESTART_AVOID_M`（1.65 m）以外的封堵点，**禁止任何 `kick()`**；`p.action` 标注 `"opp_set:avoid"` 便于赛后复盘。
3. **`src/main.py:_act_opp_kickoff`（`src/main.py:297`）**：`slots = [(-r - 0.5, 0.0), (-r - 2.0, 0.5)]` 硬编码且只考虑 +y 侧；应改为按球位镜像（`y = ±0.5`）并用 `clamp_inside_field(context, x, y, margin=0.3)` 收口，避免把球员派到边界外。
4. **`src/main.py:_act_ready`（`src/main.py:323-385`）**：两套站位共 6 个硬编码点，其中 `(-0.5, field.circle_radius + 2)` 与 `(-field.length/2 + field.penalty_area_length, 0.0)` 用场地字段算，其余是字面量。建议统一改成"字段计算 + `clamp_inside_field`"，并把两点收敛为一处 `_ready_slots(context, our_kickoff) -> list[tuple[float,float]]`，`_act_ready` 只负责 zip 分配。
5. **`src/main.py` 新增 `is_losing(context)`，但按本项目类型改写**（修掉原文 errata）：

```python
def is_losing(context: Context) -> bool:
    game = context.game
    if game is None:
        return False
    mine = game.get_team_state(context.team_id)          # 用框架自带方法，别遍历 t.team_id
    if mine is None:
        return False
    opp = next((t for t in game.teams if t.team_number != context.team_id), None)
    return opp is not None and mine.score < opp.score
```

6. **`src/main.py:_act_normal` 内部加子分支**（不新增 Phase）：`if is_losing(context) and context.game.secs_remaining < LOSING_PUSH_SECS:` → 让 `guard` 也 `attack()`；`elif is_leading and secs_remaining < HOLD_SECS:` → `support` 改回撤到小禁区前沿。新增 `src/param.py:LOSING_PUSH_SECS = 120`、`HOLD_SECS = 60`。
7. **`src/main.py:_act_normal` 守门员选择**：现在用 `min(rest, key=dist(..., own_goal))`，每帧可能换人。建议按 `store.guard_id` 做迟滞（与 `ATTACKER_KEEP_DIST_MARGIN_M` 同思路，新增 `GUARD_KEEP_DIST_MARGIN_M = 0.5`），避免门将/后卫角色抖动导致跨帧动作被打断。
8. **`src/param.py` 新增**：`SET_PLAY_TAKER_DIST_M`、`SET_PLAY_SUPPORT_DISTS_M = (1.5, 2.5)`、`LOSING_PUSH_SECS`、`HOLD_SECS`、`GUARD_KEEP_DIST_MARGIN_M`；并给 `OPPONENT_RESTART_AVOID_M = 1.65` 加注释"对方死球期间距球下限，规则阈值 1.45 m，留 0.2 m 余量"。

## 五、原文关键摘录

| Phase | 比赛场景 | 你该做什么 |
|---|---|---|
| `NORMAL` | 球是活的，六个机器人自由争抢 | 正常安排球员行动 |
| `OUR_KICKOFF` | 我方发中场球，对方必须退到中圈外 | 派人发球，其余人接应或回防 |
| `OPP_KICKOFF` | 对方发中场球，我方必须退到中圈外 | 安排防守战术，做封堵 |
| `OUR_SET_PLAY` | 我方发定位球（边线球/角球/球门球） | 从容布阵、选主罚者、设计跑位再发球 |
| `OPP_SET_PLAY` | 对方发定位球（边线球/角球/球门球） | 退到规则距离外布防、堵射门线路、盯人 |
| `READY` | 开赛前/进球后，双方走到指定站位 | 按预设站位走过去站好，不追球 |
| `STOPPED` | 比赛未开始、摆球中、暂停中、已结束 | 原地站定，什么都别做——乱动只会被罚下 |

| 角色 | 选定规则 | 行动 |
|---|---|---|
| **attacker（进攻）** | 离球最近的球员 | 追球、射门（`Player.attack()`） |
| **guard（守门）** | 剩下的人里离己方门最近者 | 站小禁区待命（`Player.guard()`） |
| **support（支援）** | 其余所有人 | 站"球-门"连线上（`Player.support()`） |

| 函数 | 原文现状 | 原文给的优化方向 |
|---|---|---|
| `_act_our_kickoff` | 锁定主罚者、写死方向踢出 | 方向随机化/按对手站位选空档；两人提前跑接应点 |
| `_act_opp_kickoff` | 一人守门 + 其余退到中圈外 | 按对方阵型调退防站位、堵第一脚出球线路 |
| `_act_our_set_play` | 直接调用 `_act_normal` | 角球传中、球门球安全出球、界外球快发偷袭；用足 10 秒布阵 |
| `_act_opp_set_play` | 直接调用 `_act_normal` | 角球堵近角+盯人、排人墙、压迫接球点；全员退到规则距离外 |
| `_act_ready` | 硬编码三个站位点 | 按球位和开球方动态布阵；站位点用场地尺寸算而非写死 |

> 因为 `_act_*` 里的代码默认假设传入的球员都能执行战术。如果把这个过滤放到分派之后……一个被罚下的球员如果恰好离球最近、被选成了 `attacker`，这一帧就没有任何人真的去抢球——不报错、不崩溃，你只是莫名其妙丢了球权。

> 看过不少参赛策略后你会发现，高分队伍的状态机并没定义更多状态，而是将状态内部的逻辑分得更细。

> 状态机不必是扁平的一层。顶层由 `Phase` 按裁判机信号划分，这一层对应比赛规则。层内你可以继续按局势细分战术，这一层往往是策略拉开差距的地方。
