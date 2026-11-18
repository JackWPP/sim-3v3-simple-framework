# 专题优化-定位球进攻

能稳定拉开比分的，往往是确定性最高的死球瞬间，也就是那些**双方都站定、时间为你所用**的定位球。本模块聚焦 `OUR_KICKOFF` 与 `OUR_SET_PLAY`，教你在定位球策略中增加配合。定位球进攻也是战术设计最容易做出亮眼效果的一环。

🎯 **学习目标**

- 读懂 `OUR_KICKOFF` 的现有逻辑
- 用两层状态机分派定位球
- 设计角球"二点进攻"配合

---

## 单元1：定位球——被低估的得分机器

真实足球里，定位球（任意球、角球、点球）贡献了职业比赛相当比例的进球。原因很简单，死球局面下，双方都站定，你可以提前排好剧本，而不是在混战中拼反应和运气。本项目里的 `OUR_KICKOFF` 与 `OUR_SET_PLAY` 阶段，就是给你写"定位球策略"的画布。现在它直接调 `_act_normal`，可以改为更有针对性的策略。

规则给了定位球发球队 10 秒钟发球时间。这 10 秒里，对方不能干扰，你可以让接应球员从容地跑向关键战术位置，把阵型排好，再在无干扰的情况下把球发出去。把死球时间变成你的"布阵窗口"就是定位球优势的来源。

在双方实力接近时，运动战往往陷入僵局，而定位球是性价比最高的得分手段。这也是为什么职业球队会专门练角球战术、任意球配合。对你的 `Agent` 来说同理。把 `OUR_KICKOFF` 与 `OUR_SET_PLAY` 写好，等于多了一套"稳定的得分套路"。

<callout emoji="💡">
**规则前提（G-03）：**定位球开出后，开球方的进球不能靠一台机器人“一气呵成”，必须满足两个条件之一：① 进球前至少有 2 台机器人触球；② 进球前的触球发生在距开球位置 0.5 m 以外。该规则适用于**所有定位球（包括球门球、角球）**，并且在球权开放（ball_free）之后仍然有效。
这意味着单人直接轰门是无效战术，下文的传球、接应配合不只是“更优解”，更是合规进球的硬性前提。
</callout>

---

## 单元2：我方开中场球逻辑 `_act_our_kickoff()`

`_act_our_kickoff`（`main.py`）代码如下：

```Python
# src/main.py（节选）
active_ids = {p.id for p in players}
if store.prev_phase != Phase.OUR_KICKOFF or store.kickoff_taker not in active_ids:
    store.kickoff_taker = _select_closest_attacker(context, players).id  # 选主罚者

attacker = next(p for p in players if p.id == store.kickoff_taker)
attacker.kick(0.1, KICK_POWER_OUR_KICKOFF)   # 朝 +x 略偏，固定力度踢出

# 其余两人：一人 guard，一人 stay（原地停）
guard = min(rest, key=...离己方门最近...)
guard.guard()
for p in rest_others: p.stop()
```

这段在做"最小可用的开球"：

- 第一段用 `store.prev_phase` 做**阶段边沿检测**，只在"刚刚进入开球阶段"或"原主罚者已不可用"时才重新选人，之后整个开球窗口都沿用同一个 id，避免每帧重选导致三个人抢着开球、原地抖动。
- 第二段直接调 **遥控器**（`Player`）的 `kick(方向, 力度)`，角度稍偏0.1弧度，避免被站在正中央的对方球员封堵。
- 第三段把剩下两人一个派去守门、一个原地站住。

**问题**：

1. 主罚者永远朝固定方向（0.1 rad）踢，对手摸清规律后轻松拦截。
2. 另外两人只是"守 + 停"，没利用开球瞬间的人数优势做接应。
3. 没有利用前面说的"开球窗口"做布阵。

<callout emoji="💡">
**规则约束（G-03）：**开球后如果只有主罚机器人 1 台触球、且在距开球点 0.5 m 以内就射门，即使球进了也无效。想让进球算数，要么让队友再触一次球（至少 2 台机器人触球），要么把球带到距开球点 0.5 m 以外再射门。下面三层升级中的“传球接应”，恰好就是满足第一条条件的标准做法。
</callout>

**升级思路**：

我们分三层来升级，一层比一层激进，你可以按自己的进度逐层实现。

**第一层：用开球窗口布阵，而不是干站着。**

规则给的 10 秒不会被对方干扰。现有代码里第三个人调的是 `stop()`，等于把这 10 秒白白扔掉。你可以考虑主罚者绕到球的后方站好，第二名球员在中场线后尽量靠前的位置，方便开球后迅速移动到接应点，第三人退到中圈偏后做保护。

**第二层：把球开向接应队友的跑动路线，而不是他现在的位置。**

新手容易忽略球滚动的时间。如果你瞄准队友**当前**的位置，队友就不得不在原地等待。正确做法是瞄准他的**前方提前量**，就是他的跑动路线上、球和他会同时到达的那个点。哪怕只是简单地取"接球点"而不是"队友当前坐标"作为瞄准目标，效果也会立刻好一大截。这样就形成了**推进**配合。

**第三层：用 `store` 记住主罚者，并按比分/局势选择开球风格。**

主罚者必须用 `store` 锁定（否则每帧重选会抖），这一点现有代码已经做对了，要保留。在此基础上可以加风格开关：

- **稳开**：短距离推给近处的队友，几乎不会丢球权，代价是推进慢，不确定性高。
- **冒险直塞**：大力斜塞到对方半场空档，成功了就是一次单刀，失败了球权立刻易手。落后时、或者比赛快结束时用它搏一把。

参考代码：

```Python
# 伪代码：开球时用 store 锁定主罚者，并按比分选择开球风格
def _act_our_kickoff_v2(context, players, store):
    active_ids = {p.id for p in players}
    if store.prev_phase != Phase.OUR_KICKOFF or store.kickoff_taker not in active_ids:
        store.kickoff_taker = _select_closest_attacker(context, players).id
        rest = [p for p in players if p.id != store.kickoff_taker]
        # 前插者：剩下人里更靠前（x 更大）的那个
        store.kickoff_runner = max(rest, key=lambda p: p.pose.x).id

    kicker = next(p for p in players if p.id == store.kickoff_taker)
    runner = next(p for p in players if p.id == store.kickoff_runner)

    # 比分差：领先则稳开，落后则直塞
    g = context.game
    us = g.get_team_state(context.team_id)
    them = next((t for t in g.teams if t.team_number != context.team_id), None)
    diff = (us.score if us else 0) - (them.score if them else 0)
    if diff > 0:
        aim = (2.0, runner.pose.y)               # 稳开：推到近处前方
        power = KICK_POWER_OUR_KICKOFF
    else:
        aim = (context.field.length / 2 - 4.0, runner.pose.y)   # 直塞：塞到对方半场
        power = KICK_POWER_MAX * 0.8

    # 前插者先跑到接球点（用满 10 秒窗口），主罚者再把球送到他的路线上
    runner.walk_to(aim, avoid_ball=True, avoid_robots=True)
    kicker.kick(angle_to(kicker.pose.x, kicker.pose.y, *aim), power)

    for p in players:
        if p.id not in (store.kickoff_taker, store.kickoff_runner):
            p.guard()
```

> 此步骤可借助AI Assistant完成，参考提示词：请帮我实现开球策略的第二层升级：主罚者用 store 锁定，另选一名前插者提前跑位，球瞄准“接应点提前量”而非队友当前位置。

---

## 单元3：定位球状态解读——两层状态机

`_act_our_set_play`（`main.py`）现在对所有定位球都只调 `_act_normal`，我们尝试用设计定位球战术对 `_act_normal` 做进一步优化。

```Python
# src/main.py（现状）
def _act_our_set_play(context, players, store):
    set_play = get_set_play_type(context)
    if set_play == SetPlay.THROW_IN:   _act_normal(...)
    elif set_play == SetPlay.CORNER_KICK: _act_normal(...)
    elif set_play == SetPlay.GOAL_KICK:  _act_normal(...)
    else: _act_normal(...)
```

注意这段代码的形式，`if/elif` 的骨架已经搭好了，只是每个分支的内容都写成了同一个 `_act_normal`。逻辑分支已经替你写好，这是框架作者故意留的填空题。当前 `_act_normal` 仅保证有人发球，没有其他战术，完全没有利用定位球的特殊性——这正是你要改的地方。

### 使用 `get_phase` 确认比赛阶段

`get_phase(context)`（`main.py`）是整套策略的**总开关**。它读裁判机状态，把比赛压缩成七个互斥的大局面：`NORMAL` / `OUR_KICKOFF` / `OPP_KICKOFF` / `OUR_SET_PLAY` / `OPP_SET_PLAY` / `READY` / `STOPPED`。

裁判机的 `set_play` 字段不是 `NONE`，说明比赛处在某种定位球状态。`kicking_team` 等于我方队号，说明这球归**我们**发。只要这两条成立，`play()` 就会把整队交给 `OUR_SET_PLAY` 分支下的 `_act_our_set_play` 处理。

**这一层只确认比赛阶段，不关心细节。** 它管的是最粗粒度、也最要命的问题：这一刻我该进攻、该避让、还是该站定？判断错了，后面写得再精妙也是白搭——比如把"对方定位球"误判成"我方定位球"，你的球员会兴冲冲跑去碰球，然后被裁判罚下。

### 使用 `get_set_play_type` 确认定位球类型

进入 `_act_our_set_play` 分支后，第二层状态机才登场。`get_set_play_type(context)`（`main.py`）直接读裁判机的 `set_play` 字段，返回定位球类型：

| 返回值 | 含义 | 进攻思路一句话 |
|-|-|-|
| `NONE` | 无定位球 | 不会走到这个分支 |
| `CORNER_KICK` | 角球 | 往禁区送，找接应点抢第二落点 |
| `GOAL_KICK` | 球门球 | 开向前场，组织推进 |
| `THROW_IN` | 界外球 | 就近短传，先保住球权 |

<callout emoji="💡">
注意：`get_set_play_type` **不区分是哪方主罚，**只确认定位球类型。
</callout>

### 状态机为什么要分层？

初学者常疑惑，为什么不直接写一个大 `if`，把"我方角球""对方角球""我方点球"……十几种情况一次分离？分层有三个好处：

1. **关注点分离**。第一层管比赛阶段，只关心“合法性”，第二层管具体场景，只关心“战术效果”。混在一起写容易状态的重复或遗漏。
2. **组合数爆炸**。两层是加法逻辑；如果变成一层，复杂组合会变成乘法逻辑。每层代码行数大幅缩减，修改某个角球战术绝不会误伤正常拼抢代码。
3. **支持渐进式迭代**。你可以今天只写好 `CORNER_KICK` 分支，其余分支继续 `_act_normal` 兜底，程序照样完整能跑。在备赛时间有限的情况下，你不需要一口气把所有定位球战术全部写完。

---

## 单元4：设计角球进攻战术

请你站在教练的位置想一个问题：当我方获得角球时，真正的挑战是什么？

球在底线角上，离球门很近，但角度极差，从发球点直接射门几乎不可能进；而且按 G-03 规则，角球与其他定位球一样，只有 1 台机器人在开球点触球的直接射门即使打进也无效，必须经过至少 2 台机器人触球、或在距开球点 0.5 m 以外触球后破门才算。所以角球的本质不是射门机会，而是一次可以自由布置的传球机会。你要解决的是三件事：

1. 球该踢到哪里？（一个既威胁球门、又容易被自己人抢到的点）
2. 谁去那儿接？（必须提前跑，不能等球飞过去才启动）
3. 万一被断了怎么办？（角球时全队压上，最怕对手一脚长传打反击）

想清楚这三件事，代码就只是把答案翻译出来而已。下面我们一步一步来。

**第一步：选主罚者。**

谁去开这个角球？答案可能是离球最近的那个人。快速发出的角球可能会让对手措手不及。项目里已经有现成的 `_select_closest_attacker(context, players)` 帮你选，直接用即可。

**第二步：选接应点。**

这是整套战术的灵魂。接应点不能选球门正前方，可能被对方门将和后卫堆满，也不能太远威胁不够。对方禁区前沿、偏向一侧的位置比较平衡，离球门足够近有威胁，但又在密集防守区外围，抢到球后可以直接推进。这个坐标就是你最该反复调的参数。

**第三步：踢向接应点，而不是球门。**

默认的 `kick()` 会调用 `plan_kick()` 瞄准对方球门中心。角球战术中，我们要用 `kick(方向, 力度)` 的双参数形式，手动把方向指定为"从发球点到接应点"。

**第四步：接应者提前跑位。**

记住那 10 秒窗口。接应者角球摆好后就开始跑，球发出时，他应该已经站在接应点上了。代码实现很简单，每帧都调 `receiver.walk_to(接应点)`，从进入角球阶段那一刻起就调。

**第五步：第三人回防。**

角球时我方两人压上，后场是空的。如果被对方解围打反击，很可能瞬间丢球。所以第三个人的任务是 `guard()`。进攻时想着防守，是成熟战术的标志。

参考代码：

```Python
# 伪代码，填入 _act_our_set_play 的 CORNER_KICK 分支
def _act_our_corner(context, players, store):
    if store.prev_phase != Phase.OUR_SET_PLAY or store.kickoff_taker is None:
        # 第一步：选主罚者（离球近的人）
        store.kickoff_taker = _select_closest_attacker(context, players).id
        # 第二步：选接应点，并让剩下人里离它最近的当接应者
        rest = [p for p in players if p.id != store.kickoff_taker]
        target = (context.field.length/2 - 3.0, 1.5)   # 对方禁区前点
        store.support_target = target
        store.receiver = min(rest, key=lambda p: dist(p.pose.x, p.pose.y, *target)).id

    kicker = next(p for p in players if p.id == store.kickoff_taker)
    receiver = next(p for p in players if p.id == store.receiver)

    # 第三步：主罚者把球踢向接应点（而非默认对方门中心）
    aim = store.support_target
    kicker.kick(angle_to(kicker.pose.x, kicker.pose.y, *aim), KICK_POWER_OUR_KICKOFF)

    # 第四步：接应者提前跑到接球点等待
    receiver.action = "corner_receive"
    receiver.walk_to(store.support_target, avoid_ball=True, avoid_robots=True)

    # 第五步：第三人退守
    for p in players:
        if p.id not in (store.kickoff_taker, store.receiver):
            p.guard()
```

开头的 `if` 是防抖闸门。中间三段分别对应第三、四、五步：`kick()` 传入了显式方向所以不会走 `plan_kick()` 的射门逻辑；`walk_to()` 带 `avoid_ball=True` 是为了让接应者跑位时绕开球，避免在球被踢出前误触（那会被判违规）；最后的 `for` 循环用"排除法"找第三人，这样即使某个球员被罚下、场上只剩两人，代码也不会崩。用 `store.support_target` 存接应点能保证主罚者瞄的点和接应者跑的点是同一个。

> 此步骤可借助AI Assistant完成，参考提示词：请帮我把上面的角球战术伪代码 \_act_our_corner 完善为可直接运行的代码，填入 \_act_our_set_play 的 CORNER_KICK 分支，并补全 store 字段声明。

<callout emoji="💡">
**关键 API**：
- `player.kick(direction, power)`：手动指定踢球方向（`player.py`）。
- `angle_to(fx, fy, tx, ty)`：从一点指向另一点的角度（`utils/geom.py`）。
- `walk_to(target, avoid_ball=, avoid_robots=)`：带避障走位（`player.py`）。
</callout>

---

## 单元5：了解 `plan_kick()`

`plan_kick()`（`player.py`）是默认射门算法。凡是你调 `attack()`，或者调不带参数的 `kick()`，最终都会落到它身上，由它决定用多大劲往哪踢。

```Python
# src/player.py
kick_target = opponent_goal(ctx)              # (length/2 + GOAL_TARGET_DEPTH_M, 0)
kick_direction = angle_to(ball.x, ball.y, *kick_target)
kick_power = KICK_POWER_BACKFIELD if self._in_backfield() else KICK_POWER_DEFAULT
```

`GOAL_TARGET_DEPTH_M`（定义于 `param.py`，默认 0.25 米）把射门目标点设在对方门线后方。这个设计解决了一个极其隐蔽的 `Bug`：当球非常贴近门线时，如果目标点刚好在门线上，球与目标的距离趋近于 0。此时向量计算的方向角会产生剧烈数值抖动，甚至因浮点误差算反——导致机器人对着自家半场踢球。把目标点往门里推 0.25 米，能确保目标始终在球的前方，保证方向角度计算恒定稳定。

这个值可以微调：调大（比如 0.5）会让射门方向更"扎实"地朝球门深处，但当球在门侧时角度会偏；调小则更贴合真实门线。没有特殊理由，建议不动它。

第二行中，angle_to(ball.x, ball.y, ...) 是从球指向目标点，而不是从机器人指向目标点。因为球才是真正飞出去的物体；若从机器人坐标计算，只要机器人没有完美站到球的正后方，击球瞬间就会产生明显的角度偏差。



`plan_kick()` 只在两个力度间二选一，但 `param.py` 里其实有四个力度参数：

| 参数 | 谁在用 | 调它的意义 |
|-|-|-|
| `KICK_POWER_DEFAULT` | `plan_kick()`（前场） | 最常调的射门力度 |
| `KICK_POWER_BACKFIELD` | `plan_kick()`（后场） | 后场大脚解围可以更猛 |
| `KICK_POWER_OUR_KICKOFF` | 开球、角球（你自己传） | 传球力度，通常小于射门 |
| `KICK_POWER_MIN` / `MAX` | `kick()` 内部夹取 | 安全护栏，超出会摔倒 |

`kick()` 内部有 `max(MIN, min(MAX, power))` 的夹取，**你传多大都不会超过 `KICK_POWER_MAX`**。这是个保护机制，防止手滑传个 100 把机器人自己踢翻。策略要在分场景给不同力度，比如后场解围要远（大力），前场射门要准（中等），传球要软（小力）。如果全场只用一个数字，某些场景下会很别扭。

当前策略射门瞄准 `opponent_goal(ctx)`，也就是球门中央。而实战中，**守门员通常就站在门中心，很容易被阻挡**。我们可以考虑以门内偏向一边为射门目标。优化的关键工具是 `kick_can_score(kick_direction)`（`player.py`）。它的作用是，给定一个踢球方向，用直线外推算出球到达门线时的横坐标 `y`，判断这个 `y` 是否落在球门宽度范围内。

---

## 📖 扩展阅读

- **RoboCup 标准平台组规则（含定位球/发球时限）**：[https://ssl.robocup.org/rules](https://ssl.robocup.org/rules)

---

## 📌 要点总结

- **定位球**可提前布置战术，且规则给了发球队 10 秒无干扰布阵窗口；
- **`OUR_KICKOFF` 当前策略粗糙，往**固定方向踢，可优化；
- **设计两层状态机，**分层让关注点分离、可逐步实现；
- **角球设计思路**：选主罚者 → 选接应点 → 踢向接应点 → 接应者提前跑位 → 第三人回防；
- **`plan_kick()`** 默认踢门中心易被扑，可优化射门角度。
- **进球规则（G-03）**：所有定位球（含球门球、角球）开出后，进球须满足至少 2 台机器人触球，或触球发生在距开球点 0.5 m 以外；球权开放后该约束依然有效，传球配合是合规得分的前提；