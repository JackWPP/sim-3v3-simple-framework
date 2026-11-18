# 专题优化-分区策略

很多策略写死了球队的阵型和分工，缺乏针对场面的动态调整。一些聪明的策略会根据**球落在场地的哪个区域**，动态切换整队的站位与角色：球在我方禁区前沿，全员回收死守；球压到对方半场，前锋压上、支援前插。这一篇教你把场地分区，再据此换阵型、换分工。

🎯 **学习目标**

- 用两个参数把场地切成三区；
- 知道每区该"谁干什么"；
- 写出完整的三分区 `_act_normal`。

---

## 单元1：为什么要分区？

前几篇介绍的角色分配（`attack/guard/support`）有一个共同特点：**只关心"谁离球最近"**，不关心"球在哪片区域"。不管球是在我方禁区前沿，还是在对方半场，离球最近的那个人永远去追球，其他人按固定分工站位。

这种"一刀切"的策略在简单场景下够用，但面对复杂局面就会暴露问题。举个例子：球在我方禁区前，对方球员正准备射门——这时如果还按"离球最近的人去追"，很可能只有一个人在防守，其他人还在前面等着进攻，球门直接暴露给对手。反过来，球压到对方半场了，所有人还保持着防守阵型，白白浪费了进攻人数优势。

现代足球的核心思想是**控制空间**——通过占据关键区域来逼迫对手、创造机会。分区策略就是"控场"的最简实现：我们显式定义哪些区域是"关键空间"，然后让球队的行为随空间位置动态变化。

**高位逼抢**就是最典型的例子：当球在对方半场时，全员压上、就近逼抢，把对手压缩在狭小空间里，迫使他们失误丢球。这背后的几何逻辑很简单——球离对方球门越近，我们丢球后的回防距离就越长，所以必须用人数优势把危险扼杀在源头。

反过来，**低位防守**就是当球在自己半场时，全员退守、压缩禁区前沿的空间。因为球离我们的球门近，一旦被突破就是直接威胁，所以宁可放弃前场的逼抢，也要保证门前的防守密度。

<callout emoji="💡">
**一句话理解分区策略：**球离我的门近，就要更重视防守；球在对方门口，就应该大胆压上。
</callout>

理解了空间的重要性之后，我们来针对不同区域设计更细腻的策略。

---

## 单元2：场地分区定义方式

3V3仿真赛场地 `length=14m`、`width=9m`，中心 `(0,0)`，己方门在 `-x`、对方门在 `+x`（`types.py`）。分区会**把连续的 `ball.x`（有时还要看 `ball.y`）映射到几个区间**。

分得太粗，比如只分"我方半场/对方半场"，等于没分。因为刚过中线和对方门前的威胁程度天差地别；分得太细，比如切成五档、七档，又会让阵型高频切换，球员容易抖动，产生混乱。你可以结合自己的战术设计划分方案。

这里以三等分为例，示范一个简单的动态策略：

| 球的位置 | 位置最靠后的球员 | 位置第二靠后的球员 | 位置第三靠后的球员 |
|-|-|-|-|
| 场地前 1/3 | 守门员 | 进攻角色 | 进攻角色 |
| 场地中间 1/3 | 守门员 | 防守角色 | 进攻角色 |
| 场地后 1/3 | 守门员 | 防守角色 | 防守角色 |

这个表格的核心逻辑是：**球越靠近我方球门，防守人数越多；球越靠近对方球门，进攻人数越多**。具体来说：

- **前场（进攻区）：**球离对方门最近，我们有最大的进球机会，所以派2人去进攻，只留1人兜底守门，最大化进攻压力。
- **中场（过渡区）：**球在中间，攻守平衡，1守1攻1支援，保持阵型弹性。
- **后场（危险区）：**球离我方门最近，丢球就是直接威胁，所以守门员外，派2人防守，优先保证球门安全。

<figure view-type="Preview"><source name="根据球位置分配角色示意图-可拖动查看效果.html" mime="text/html" size="28020" token="RheibDCZkox97GxxCq3c4ZZhnIf"/></figure>

上面的"前1/3、中1/3、后1/3"是等距划分，但实际比赛中我们往往需要**不对称划分**——防守的安全区和进攻的压上区不一定一样宽。为此我们设计两个可调参数 `DANGER_X` 和 `ATTACK_X`：

- `DANGER_X`：危险区右边界。当 `ball.x < DANGER_X` 时，球进入我方危险区，切换为防守优先阵型。
- `ATTACK_X`：进攻区左边界。当 `ball.x > ATTACK_X` 时，球进入对方进攻区，切换为进攻优先阵型。
- 两者之间就是中间过渡区，保持标准攻守平衡。

可以使用以下代码判断区域：

```Python
if ball.x < DANGER_X:
    zone = "danger"
elif ball.x > ATTACK_X:
    zone = "attack"
else:
    zone = "middle"
```

<callout emoji="📝">
**参数参考值与调参建议：**
- 场地总长14m，从-7到+7。初始可以设 `DANGER_X = -2.5`、`ATTACK_X = 2.5`，即危险区和进攻区各约占场地1/3。
- **觉得防守不稳？**把 `DANGER_X` 调大（比如调到-1.5），危险区范围变大，更早切换防守阵型。
- **想更激进进攻？**把 `ATTACK_X` 调小（比如调到1.5），进攻区范围变大，更早压上进攻。
- **注意：**两个参数不要设得太接近，否则球在中线附近来回移动时会频繁切换阵型，导致球员抖动。建议至少相差2m以上。
</callout>

<callout emoji="💡">
上面的划分**只关注 `ball.x`**，因为纵向位置决定了"该压上还是该回收"。有时横向位置也有战术价值。
</callout>

在变量 `zone` 获得了球所在的区域后，我们可以使用状态机的思路，写出三个区域的分支：

```Python
if zone == "danger":
    pass
elif zone == "attack":
    pass
else: # zone == "middle"
    pass
```

接下来，我们只需要完善三个分支中的角色分配逻辑即可。你也可以把我们这里的分支当作状态机的第二层设计，我们把之前 `Phase.NORMAL` 按区域做了细分。

---

## 单元3：把分区策略接入 `_act_normal`

下面是把上面三区完善后的完整 `_act_normal`。它**直接替换** `src/main.py` 中的同名函数即可使用。

```Python
def _act_normal(context: Context, players: list[Player], store) -> None:
    """NORMAL: 三分区切换。危险区→2 guard + 1 attack，攻击区→2 attack + 1 guard，中间→标准。"""
    if not players:
        return

    ball = context.ball

    # ── 第1步：看球在哪，选区域 ──
    if ball.x < DANGER_X:
        zone = "danger"
    elif ball.x > ATTACK_X:
        zone = "attack"
    else:
        zone = "middle"

    # ── 第2步：按区分配角色 ──
    if zone == "danger":
        # 我方危险区：2 人守门 + 1 人追球
        attacker = _select_closest_attacker(context, players)
        attacker.action = "attack"
        attacker.attack()

        rest = [p for p in players if p is not attacker]
        for p in rest:
            p.guard()

    elif zone == "attack":
        # 对方危险区：2 人前压抢球 + 1 人兜底守门
        gx, gy = own_goal(context)
        guard = min(players, key=lambda p: dist(p.pose.x, p.pose.y, gx, gy))
        guard.guard()

        rest = [p for p in players if p is not guard]
        for p in rest:
            p.action = "attack"
            p.attack()

    else:
        # 中间区域：标准攻/守/援三角（保留原版逻辑，含 attacker 迟滞）
        attacker = _select_closest_attacker(
            context, players, getattr(store, "normal_attacker", None),
        )
        store.normal_attacker = attacker.id
        attacker.action = "attack"
        attacker.attack()

        rest = [p for p in players if p is not attacker]
        if rest:
            gx, gy = own_goal(context)
            guard = min(rest, key=lambda p: dist(p.pose.x, p.pose.y, gx, gy))
            guard.guard()
            rest = [p for p in rest if p is not guard]

        for p in rest:
            p.action = "support"
            p.support()
```

这段代码包含了完整的分区策略逻辑。我们逐段拆解一下：

**第1步：区域判断**（代码第8-14行）

用 `ball.x` 和两个阈值比较，把球的位置映射成 `danger`、`attack`、`middle` 三种状态。这一步是整个策略的"大脑"——后面所有行为都取决于当前在哪个区。

**第2步：危险区分支**（代码第17-24行）

球在我方危险区时，策略是**"先保球门，再谈抢球"**：选离球最近的人去追球干扰，剩下两个人全部守门。注意这里的 `attacker` 其实是"去追球的人"，不是传统意义上的前锋——在危险区，追球的目的是干扰对方传球和射门，而不是带球进攻。

**第3步：进攻区分支**（代码第26-34行）

球在对方半场时，策略是**"全力压上，只留一人兜底"**：选离我方球门最近的人当守门员（防止被打反击），剩下两个人全部压上去抢球和进攻。人数优势是这里的关键——2打1的逼抢很容易迫使对方失误。

**第4步：中间区分支**（代码第36-51行）

中间区是过渡地带，我们保留了原版的标准三角阵型：1人追球、1人守门、1人支援。这样做有两个原因：一是中间区攻守平衡，不需要极端倾斜；二是原版逻辑里有 `attacker` 迟滞机制（防止追球的人频繁切换导致抖动），在过渡区保留这个机制更稳定。

到这里，一个完整的三分区动态策略就实现了。但这只是起点，你还可以沿着这些方向继续优化：

- **更细的区域划分：**从三区扩展到五区甚至七区，每个区域对应更精细的阵型。但要注意：区域越多，切换越频繁，越容易出现抖动。
- **加入横向判断：**同时看 `ball.x` 和 `ball.y`，把场地分成九宫格，边路和中路采用不同的战术安排。
- **动态调整阈值：**根据比分、剩余时间动态调整 `DANGER_X` 和 `ATTACK_X`——比如落后了就把进攻区往前推，领先了就把危险区扩大加强防守。

> 此步骤可借助AI Assistant完成，参考提示词：请帮我实现完整的三分区 \_act_normal 策略（danger 2守1攻 / attack 2攻1守 / middle 标准三角色），并在此基础上扩展为“加入 ball.y 横向判断的九宫格”或“按比分动态调整 DANGER_X / ATTACK_X”。

---

## 📖 扩展阅读

- **高位逼抢 / 低位防守（high press / low block）几何含义**：[https://footballcoach365.com/3-types-of-blocks-how-to-defend-zonal-marking](https://footballcoach365.com/3-types-of-blocks-how-to-defend-zonal-marking)
- **区域盯人（zonal marking）详解**：[https://guidetofootball.com/tactics/zonal-marking](https://guidetofootball.com/tactics/zonal-marking)

---

## 📌 要点总结

- 分区策略的核心是**按球所在区域动态切换整队阵型**——球离谁的门近，谁就更重视防守；
- 用 `DANGER_X` 和 `ATTACK_X` 两个参数把场地切成三区，用 `ball.x` 判断当前区域；
- 进阶方向：加入 `ball.y` 的横向判断、动态调整阈值、增加过渡状态，让策略更灵活细腻。