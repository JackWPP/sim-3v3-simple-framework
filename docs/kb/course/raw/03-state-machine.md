# 深入理解状态机

这一篇我们进入 `play()` 内部，讨论战术引擎的核心——**状态机**。状态机解决策略中最重要的问题："此刻是什么局面，我该用哪套打法？"答错这一步，再漂亮的进攻套路也会用错时机，甚至被判违规。

🎯 **学习目标**

- 认识七种 `Phase` 比赛阶段；
- 读懂 `get_phase` 判定优先级；
- 了解 `play()` 每帧的执行顺序；
- 掌握角色分配逻辑；
- 学会给状态机加分层。

---

## 单元1：为什么需要状态机？

路口有明确的"通行 / 等待"状态，车辆遵循指示才不会撞成一团。足球比赛中类似，同一套代码，在开球瞬间、对方任意球、正常拼抢等不同场景中，行为应该完全不同。

状态机（FSM，Finite State Machine）就是显式表示当前局势，再针对局势设计行为逻辑。本项目用 `Phase` 枚举来充当红绿灯。

有限状态机是计算机科学里最基础、实用的模型之一。系统在任何时刻处于有限个状态之一，并根据输入切换状态。如果你想加一种新情况（比如"我方落后"），就加一个 Phase 和对应的 `_act_*`，不会牵一发而动全身。有人觉得状态机很土、应该用更花哨的 AI。但事实是机器人足球框架普遍采用状态机来组织决策。因为它可解释、可控、好调试。等你真的在赛场上被一个诡异 bug 折磨时，你会感谢"状态一眼就能看明白"的设计。

---

## 单元2：七种比赛阶段 Phase 枚举

`src/main.py` 定义了 `Phase`，我们来看代码：

```Python
# src/main.py
class Phase(Enum):
    NORMAL = "normal"              # 正常拼抢（比赛的主体时间，双方自由争抢）
    OUR_KICKOFF = "our_kickoff"    # 我方开中场球（中圈开球，由我方先触球）
    OPP_KICKOFF = "opp_kickoff"    # 对方开中场球（我方须退守、不能干扰）
    OUR_SET_PLAY = "our_set_play"  # 我方定位球（任意球/角球/点球/球门球，我方主罚）
    OPP_SET_PLAY = "opp_set_play"  # 对方定位球（我方须避让、布防）
    READY = "ready"                # 走位状态（开赛前、进球后、半场等，须回到指定站位）
    STOPPED = "stopped"            # 暂停/未开始/结束（SET/INITIAL/FINISHED/无裁判数据）
```

定义 `Phase` 使用 Python 的 `Enum` 枚举类，而不是字符串或整数常量。枚举有三个优势：

1. 写错立即报错；
2. IDE 能自动补全，你不用背七个名字；
3. 打印友好，方便调试。

Phase 的命名成对出现（`OUR_` / `OPP_`），因为同一类定位球，主罚方和防守方的动作完全相反，须分开处理。将每一个枚举 Phase 对应到真实比赛场景，这是理解整个项目的关键：

| Phase | 比赛场景 | 你该做什么 |
|-|-|-|
| `NORMAL` | 球是活的，六个机器人在场上自由争抢 | 正常安排球员行动 |
| `OUR_KICKOFF` | 我方发中场球，对方必须退到中圈外 | 派人发球，其余人做好接应或回防 |
| `OPP_KICKOFF` | 对方发中场球，我方必须退到中圈外 | 安排防守战术，做封堵 |
| `OUR_SET_PLAY` | 我方发定位球（边线球/角球/球门球） | 从容布阵、选好主罚者、设计跑位再发球 |
| `OPP_SET_PLAY` | 对方发定位球（边线球/角球/球门球） | 退到规则距离外布防、堵射门线路、盯人 |
| `READY` | 开赛前 / 进球后 ，双方走到指定站位 | 按预设站位点走过去站好，不追球 |
| `STOPPED` | 比赛未开始、摆球中、暂停中、已结束 | 原地站定，什么都别做——乱动只会被罚下 |

Phase 由 `get_phase`函数计算，返回 7 种 Phase 之一。你可以根据策略需要，增加状态种类，设计更精细的策略。比如你想专门处理"我方落后且比赛快结束"的局面，可以基于 `GameControlState` 自己返回一个新 Phase，或是在 `_act_normal` 内部再细分。

<callout emoji="💡">
建议选手先熟悉 7 个基本 Phase。现有 Phase 无法满足新战术时再加状态。每加一个状态，就需要设计一段专用逻辑，会提高复杂度。新手常犯的错误是上来就定义大量状态，结果一半从不被触发，反而把自己绕晕。
</callout>

你可以把我方定位球阶段 `OUR_SET_PLAY` 细分，针对不同种类的定位球设计战术。比如你额外定义了 `Phase.OUR_CORNER`，就能写一套专门的角球战术，我们将在<cite doc-id="GYriwP4YMiKeIrkyzCzc20pOnK3" file-type="wiki" title="专题优化-定位球进攻" type="doc"></cite>讨论。

> 此步骤可借助AI Assistant完成，参考提示词：请帮我新增一个 Phase.OUR_CORNER 枚举状态，并在 play() 的状态机分派中加入对应分支，再写一个基础的 \_act_our_corner 角球战术函数。

## 单元3：使用 `get_phase` 计算 Phase

获得 phase 的计算逻辑在 `get_phase(context)`，位于 `src/main.py`。它读 `context.game`（裁判机数据），并判定当前 Phase：

```Python
# src/main.py（节选，已精简注释）
def get_phase(context: Context) -> Phase:
    g = context.game
    if g is None:
        return Phase.STOPPED                       # ① 没裁判数据 → 停

    state = g.state
    if state == GameState.READY:
        return Phase.READY                         # ② READY 走位

    if state == GameState.PLAYING and not g.stopped:
        if g.set_play != SetPlay.NONE and g.kicking_team != KICKING_TEAM_NONE:
            return Phase.OUR_SET_PLAY if g.kicking_team == our_team \
                   else Phase.OPP_SET_PLAY         # ③ 定位球
        if g.secondary_time > 0 and g.kicking_team != KICKING_TEAM_NONE:
            return Phase.OUR_KICKOFF if g.kicking_team == our_team \
                   else Phase.OPP_KICKOFF          # ④ 开球
        return Phase.NORMAL                        # ⑤ 正常拼抢

    return Phase.STOPPED                           # ⑥ SET/INITIAL/FINISHED
```

这段代码中，每层判断一旦成立就立刻 `return`，代码的物理顺序就是逻辑的优先级顺序，没有深处嵌套 `else`，非常清晰。顺序从"最不该动"逐级走向"可以自由发挥"。我们拆成三层来理解：

1. 先排除"非比赛状态"（①②⑥）。它们代表现在不该按比赛逻辑行动。比赛还没开始你就去追球，裁判机断线了你却照常进攻，都是犯规。这些情况下，唯一正确的动作是站住别动或走到指定位置。所以第一时间把它们挑出来，后面的代码可以放心假设"比赛正在进行"。就像开车前先确认车况是否正常，因为它一旦异常，别的都不重要了。
2. 再分辨"该谁发球"（③④）。 确认比赛确实在进行后，第二个要问的问题是"球现在是自由的，还是属于某一方的"。定位球和开球都属于"球有归属"的死球局面，此时主罚方和防守方的动作完全相反：主罚方要抢时间把球发出去、要设计接应跑位；防守方要退到规则距离外、要堵线路、绝对不能上抢。同一场景，两方却要执行相反策略，靠 `kicking_team == our_team` 判断把逻辑分为 `OUR_` 和 `OPP_` 两个分支。
3. 最后用 `NORMAL` 兜底（⑤）。正常拼抢是默认状态。只有当"不是暂停、不是走位、不是定位球、不是开球"这四件事全都成立时，才轮到它。越特殊、越不能乱来的局面，优先级越高。`NORMAL` 是自由度最大的状态，放在最后。

例子：假设比赛正常进行中，我方 3 号在边路把球撞出了底线，裁判判对方角球。这一帧发生了什么？

- 先看 ①：裁判数据在，跳过。
- 再看 ②：`state` 是 `PLAYING` 不是 `READY`，跳过。
- 走到 ③：`set_play == CORNER_KICK`（不是 `NONE`），且 `kicking_team` 是对方 → 立刻返回 `Phase.OPP_SET_PLAY`，后面的 ④⑤ 根本不会执行。
- `play()` 于是把 `active` 交给 `_act_opp_set_play`，你的球队开始退防：一人回到门前守住近角，其余人站到规则要求的距离外堵传中路线。没有任何人冲上去抢球。

如果没有这条优先级链，你直接判断"球是活的就用 `_act_normal`"，那么对方角球时，你离球最近的球员会兴冲冲地冲到球边上去抢——结果是被判违规离场。

> **`secondary_time` 的作用**
> 
> 开球（`kick-off`）有一个短暂的"允许触球"窗口，由 `secondary_time > 0` 表示。`get_phase` 靠它区分"正在开球"和"已经开球完毕进入正常拼抢"，所以你会在开球窗口内看到 `OUR_KICKOFF`/`OPP_KICKOFF`，窗口一过立刻回到 `NORMAL`。这也是为什么开球逻辑必须"赶在窗口内把球踢出去"。

---

## 单元4：`play()` 中的状态机设计

`play()`（`main.py`）的每帧处理流程如下：

分岔之前是 `play()` 每帧都要做的准备工作，根据 Phase 分岔后会走其中一条：

1. **算 Phase + 记录 phase 边沿**

```Python
phase = get_phase(context)
store.prev_phase = store.cur_phase
store.cur_phase = phase
```

这一步做了个滑动窗口，每帧把新值往前推一格，旧值放入 `prev_phase`。

`play()` 是静态方法，每帧被重新调用，函数内的局部变量不保留，只有 `store` 里的数据能跨帧存活。这也是本项目里"记忆"的唯一正确落点。相邻两帧的 Phase，可以用来检测 Phase 边沿，也就是判断是不是这一帧切进的当前状态。

`if store.cur_phase != store.prev_phase:` 成立，说明状态刚发生跳变。很多只做一次的动作，比如进入我方开球时要"锁定一个主罚者"，如果每帧都重选，球员会在两个人之间来回横跳、谁也没真的去踢球（`_act_our_kickoff` 里 `store.kickoff_taker` 正是靠这个机制维持稳定）。

这类`进入某状态时执行一次`的逻辑，全靠边沿检测。`store` 的更多玩法（迟滞、计数、冷却）可参考<cite doc-id="QhaYwC8SniGAiukUQmxcQ9uZnkc" file-type="wiki" title="使用store设计跨帧策略" type="doc"></cite>。

1. **活性自理**

遍历每个 `Player`，把"本帧真正能做事的人"放入 `active` 列表：

- `p.ensure_ready()`：摔倒就起身、没在 `walk` 模式就切模式。这一步对所有人都做，包括被罚下的——这样罚时一到，他解禁那一帧就已经站好了，能立刻投入比赛。
- 被罚下（`is_penalized`）→ 只能起身/切模式，不能移动，直接 `stop()`。
- 还没就绪（正在爬起来、正在切模式）→ 这帧别指望他，交给 `ensure_ready()` 自己处理。
- 自己位姿未知（`pose is None`）→ 不参与分派，因为它连自己在哪都不知道，让它跑就是乱跑。
- 只有"健康且已知位置"的球员进入 `active` 列表。

1. **if/elif 选择 Phase 分支**

根据 Phase 调用对应的 `_act_*`，把 `active` 传进去。这条链只做转交，不做战术判断。保证每帧有且只有一个 `_act_*` 被执行，杜绝"两个函数同时指挥同一个机器人"的混乱。

`NORMAL` 之外的每个分支还会先调 `_clear_normal_sticky(store)`，清空 `NORMAL` 阶段记住的"进攻者"，避免死球结束回到 `NORMAL` 时沿用过时的旧决定。

```Python
if phase == Phase.NORMAL:
    _act_normal(context, active, store)

elif phase == Phase.OUR_KICKOFF:
    _clear_normal_sticky(store)
    _act_our_kickoff(context, active, store)

elif phase == Phase.OPP_KICKOFF:
    _clear_normal_sticky(store)
    _act_opp_kickoff(context, active)

elif phase == Phase.OUR_SET_PLAY:
    _clear_normal_sticky(store)
    _act_our_set_play(context, active, store)

elif phase == Phase.OPP_SET_PLAY:
    _clear_normal_sticky(store)
    _act_opp_set_play(context, active, store)

elif phase == Phase.READY:
    _clear_normal_sticky(store)
    _act_ready(context, active)

elif phase == Phase.STOPPED:
    _clear_normal_sticky(store)
    for p in active:
        p.action = "stopped"
        p.stop()
```

对于所有 `_act_*` 方法，输入仅限 `context`、`active` 和 `store`。即策略通常依据这三个变量计算出机器人的行动指令。后面三个模块，我们会对这三个变量逐一讲解。

> **为什么"活性自理"要在分支之前？**
> 
> 因为 `_act_*` 里的代码默认假设传入的球员都能执行战术。如果把这个过滤放到分派之后，某个 `None` 位姿的球员一旦被调 `attack()`，就可能在内部解引用 `pose.x` 时崩溃。比如，一个被罚下的球员如果恰好离球最近、被选成了 `attacker`，这一帧就没有任何人真的去抢球——不报错、不崩溃，你只是莫名其妙丢了球权。

---

## 单元5：比赛正常阶段的策略逻辑 `_act_normal()`

正常拼抢下，状态机将进入 `Phase.NORMAL` 分支的 `_act_normal()`。这个分支中，三个机器人被分成三种角色（`main.py`），代码如下：

```Python
# src/main.py（节选）
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

函数用逐层剥离的方式指派角色**。**先选出最该进攻的球员，把他从候选池里拿掉；再在剩下的人里选出守门员，又拿掉；其余全部做支援。不管场上是 3 个人、2 个人还是 1 个人，这种写法都能正确工作。

选 attacker 时，参数传入了 `store.normal_attacker`（上一帧的进攻者 id）是在做**迟滞**。只要之前进攻者没落后太多，就继续让他打，避免两人距离很近时角色抖动。

**`_act_normal` 分派流程图：**

| 角色 | 选定规则 | 行动 |
|-|-|-|
| **attacker（进攻）** | 离球最近的球员 | 追球、射门（`Player.attack()`） |
| **guard（守门）** | 剩下的人里离己方门最近者 | 站小禁区待命（`Player.guard()`） |
| **support（支援）** | 其余所有人 | 站"球-门"连线上（`Player.support()`） |

`_act_normal` 中，策略先分配角色（`attack` / `guard` / `support`），再指挥角色行动。角色（`role`）独立于球员（`player id`），这样设计的好处：

1. 动态分工：离球最近的球员这帧是 `attacker`，下一帧球被别人抢走、它离门最近了，就自动变成 `guard`。有人被罚下、有人摔倒等情况发生时，策略会高频评估后，分配球员最适合的角色。
2. 战术和职责解耦。策略时只思考"需要一个进攻者、一个守门者、一个支援者"，而不必管具体是 1 号还是 3 号在干。解耦后，代码更易读、更易改。比如你想把"支援者"改成"第二进攻点"，改 `support()` 即可，不用动分派逻辑。
3. 便于做出更复杂的阵型。你可以进一步优化分配角色的逻辑，比如"球在前场时，让最靠前的两人都进攻、只留一人回防"。

上述角色分派有一个隐含前提：传进 `_act_normal` 的 `players` 参数，是 `play()` 里已经筛好的 `active` 列表。列表只包含"健康、未被罚下、且位姿已知"的球员。

规则上，罚下的人不能动，因此不应该参与角色分配。可他人还站在场上、坐标也是有效的，从纯数学视角，他完全可能是"离球最近的那个"。一旦把他选成 `attacker`，`attacker.attack()` 立即生效，这个机器人会再次触发犯规，刷新罚站时间。而你的代码却认为已经派出了进攻者，于是剩下两人一个守门、一个支援。结果全队没有一个人去抢球，眼睁睁看着对方把球带走。这个 `bug` 不会报错、不会崩溃，只会让你输球，是最难排查的那一类。

<callout emoji="💡">
注意：只从 `active` 里挑人，被罚下者不参与任何角色分派。项目里 `play()` 已经替你做好了这层过滤，你自己新写 `_act_*` 时也要遵守同样的契约。
</callout>

> 例子：2 号被罚下，剩下两人怎么补位？ 假设正常拼抢中 2 号（原本在守门）被罚下，`active` 里只剩 1 号和 3 号。`_act_normal` 照常运行，只是候选池从 3 人变成 2 人。
> 
> - 1 号此刻离球最近 → 选为 `attacker`，继续追球。
> - `rest` 里只剩 3 号 → 它自动成为离己方门最近者，被选为 `guard`，回撤补上 2 号空出来的门前位置。
> - `rest` 清空，没有人当 `support`——这一帧就是"一攻一守"的应急阵型。

这体现了角色独立于球员的合理之处。策略不会因减员崩溃，阵型可以自动收缩。**你只要优先分配更重要的角色即可。**

---

## 单元6：状态机的留白等你来填

示例策略只把 `NORMAL` 和 `OUR_KICKOFF`/`OPP_KICKOFF` 写得比较完整，定位球（`SET_PLAY`）直接调用 `_act_normal`。这是留给你的优化空间：

| 函数 | 现状 | 可优化方向 |
|-|-|-|
| `_act_our_kickoff` | 锁定主罚者、写死方向踢出 | 开球方向随机化或按对手站位选空档；让另两人提前跑到接应点，把开球变成一次有预谋的进攻 |
| `_act_opp_kickoff` | 一人守门 + 其余退到中圈外 | 按对方阵型动态调整退防站位，堵住最可能的第一脚出球线路；提前站到"由守转攻"最有利的位置，抢断后能立刻反击 |
| `_act_our_set_play` | 目前直接调用 `_act_normal` | 按定位球类型分别写战术：角球写传中战术，球门球写安全出球路线，界外球写快发偷袭。利用规则给的 10 秒从容布阵 |
| `_act_opp_set_play` | 目前直接调用 `_act_normal` | 按对方定位球类型布防：角球堵近角+盯人，球门球排人墙挡角度，界外球压迫接球点。全员退到规则距离外，避免二次犯规 |
| `_act_ready` | 硬编码三个站位点 | 按球位置和开球方动态布阵：我方开球时站进攻阵型，对方开球时站防守阵型；三个站位点用场地尺寸算出来而非写死 |

看过不少参赛策略后你会发现，高分队伍的状态机并没定义更多状态，而是将状态内部的逻辑分得更细。这里给三个典型例子：

1. **落后压上、领先收缩**。读裁判机的比分，在 `NORMAL` 内部再分两套打法：落后时把 `guard` 也推到中场当第二进攻点，用防守风险换进球概率；领先时反过来，让 `support` 回撤成第二后卫，宁可不进球也不丢球。让战术充分考虑比分信息。
2. **终场前死守 / 搏命**。结合剩余时间做决策：比赛还剩十几秒且我方 1 球领先时，全员回收禁区、把球往边路和前场大脚解围，不给对方任何机会；落后时则连门将都压上去。同样的比分，比赛剩 5 分钟和剩 10 秒的最优解完全不同，时间维度值得单独判断。
3. **按球的位置细分打法**。在 `NORMAL` 内部先判断球在哪个区域：球在对方禁区就全线压上、敢投兵力；球在中场维持标准站位；球在自家禁区就全员回收、优先解围而不是组织。这套思路<cite doc-id="PRTgwO9S9iFBYEkmroic1Yp1nJh" file-type="wiki" title="专题优化-分区策略" type="doc"></cite>会展开讲。

这三类优化有一个共同点：它们都没有新增顶层 Phase，而是在已有 Phase 内部再做判断。下面给出一个参考策略代码：落后时让所有可行动球员转为进攻（写在 `NORMAL` 分支内）。

```Python
# src/main.py —— 可直接粘贴使用
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

`is_losing()` 判断是否落后，不给任何球员下指令，所以它可以在任何地方安全调用（画调试信息、写日志、给别的战术当条件）。`_act_all_out_attack()` 只管执行，不关心原因。

> 此步骤可借助AI Assistant完成，参考提示词：请帮我基于“判断与执行分离”的思路，把触发条件从“落后”改成“落后且剩余时间不足两分钟”，并新增一个“领先时全员回收”的 \_act\_ 函数。

判断与执行分离让两边都能独立替换。如果你想把触发条件从"落后"改成"落后且剩余时间不足两分钟"，只改 `is_losing`；想把压上方式从"全员 `attack`"改成"留一人接应"，只改 `_act_all_out_attack`。

改好的策略在 `play()` 里接入到 `Phase.NORMAL` 分支：

```Python
# src/main.py（play 内，if/elif 分派处）
if phase == Phase.NORMAL:
    # NORMAL 内部再分一层：按比分选打法
    if is_losing(context):
        _act_all_out_attack(context, active, store)   # 落后 → 全员压上
    else:
        _act_normal(context, active, store)           # 正常 → 标准三角色
elif phase == Phase.OUR_KICKOFF:
    _act_our_kickoff(context, active, store)
# ... 其它分支不受影响
```

"落后压上"是 `NORMAL` 的子分支，而不是一个和 `NORMAL` 并列的 Phase。因为全员压上不是一种**比赛局面**，而是一种**战术倾向**——它和裁判机判定的开球、定位球完全不是一个维度的东西。

如果你把它做成并列的新 Phase（比如加一个 `Phase.LOSING`），会产生很多额外的逻辑冲突：对方任意球时我方也落后，这时该走 `OPP_SET_PLAY` 还是 `LOSING`？两个都想要，可状态机只能选一个。而放进 `NORMAL` 内部，顶层依然由裁判机说了算，你的战术偏好只在"活球自由发挥"的时候才生效，死球局面照常守规矩。这种写法的改动面极小，其它分支一个字都不用动。

<callout emoji="💡">
**状态机可以是多层的**
</callout>

状态机不必是扁平的一层。顶层由 `Phase` 按裁判机信号划分，这一层对应比赛规则。层内你可以继续按局势细分战术，这一层往往是策略拉开差距的地方。

划分状态机的层次可以依据以下原则：外部规则决定的东西放顶层，你自己的战术偏好放内层。想清楚"这个判断是裁判机告诉我的，还是我自己想这么打的"，就知道它该放在哪一层了。

---

## 📖 扩展阅读

- [有限状态机（FSM）基础Wikipedia ](https://en.wikipedia.org/wiki/Finite-state_machine)
- **行为树 vs 状态机**：本项目使用状态机；业界也有用行为树（Behavior Tree）组织复杂决策的。本项目**未使用**行为树，但你可在学有余力时对比两者优劣。[Wikipediea](https://en.wikipedia.org/wiki/Behavior_tree_(artificial_intelligence,_robotics_and_control))。

---

## 📌 要点总结

- `Phase` 枚举用 7 种阶段（NORMAL / 开球×2 / 定位球×2 / READY / STOPPED）；
- **`get_phase` 按优先级翻译裁判机信号；**
- **`play()` 每帧三步走**：算 Phase → 活性自理（过滤罚下/无位姿）→ if/elif 分派到 `_act_*`；
- **`_act_normal` 三角色**：离球最近→`attack`，离己方门最近→`guard`，其余→`support`；
- `OUR/OPP_SET_PLAY`、`_act_ready` 目前是占位实现，是你写出差异化战术的入口。