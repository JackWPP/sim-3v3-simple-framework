# 11 专题优化-分区策略
> 来源：https://booster.feishu.cn/wiki/PRTgwO9S9iFBYEkmroic1Yp1nJh（原文约 6000 字）

## 一、战术剧本 / 核心要点

- **要解决的问题**【原文】：`attack/guard/support` 这套角色分配只关心"谁离球最近"，不关心"球在哪片区域"。球在我方禁区前、对方正要射门时，仍只有一个人防守，其他人还在前面等进攻，球门直接暴露；反过来球压到对方半场，所有人还保持防守阵型，白白浪费人数优势。
- **核心思想**【原文】：控制空间——显式定义哪些区域是"关键空间"，让球队行为随空间位置动态变化。一句话：**球离我的门近，就要更重视防守；球在对方门口，就应该大胆压上。**
- **两种极端形态**【原文】：**高位逼抢** = 球在对方半场时全员压上、就近逼抢，几何逻辑是"球离对方球门越近，我们丢球后的回防距离就越长，所以必须用人数优势把危险扼杀在源头"；**低位防守** = 球在自己半场时全员退守、压缩禁区前沿空间，宁可放弃前场逼抢也要保证门前防守密度。
- **场地基准**【原文】：3V3 场地 `length=14 m`、`width=9 m`，中心 `(0,0)`，己方门在 `-x`、对方门在 `+x`（`types.py`）。分区就是把连续的 `ball.x`（有时还要看 `ball.y`）映射到几个区间。
- **分区粒度**【原文】：太粗（只分"我方半场/对方半场"）等于没分，因为刚过中线和对方门前的威胁程度天差地别；太细（五档、七档）会让阵型高频切换，球员抖动混乱。
- **三等分角色表**【原文】（"位置最靠后"指离己方门最近）：

| 球的位置 | 最靠后的球员 | 第二靠后的球员 | 第三靠后的球员 |
|---|---|---|---|
| 场地前 1/3（进攻区） | 守门员 | 进攻角色 | 进攻角色 |
| 场地中间 1/3（过渡区） | 守门员 | 防守角色 | 进攻角色 |
| 场地后 1/3（危险区） | 守门员 | 防守角色 | 防守角色 |

  核心逻辑：**球越靠近我方球门，防守人数越多；球越靠近对方球门，进攻人数越多**。前场派 2 人进攻只留 1 人兜底守门，最大化进攻压力；中场 1 守 1 攻 1 支援保持弹性；后场守门员之外派 2 人防守，优先保证球门安全。
- **两个可调阈值**【原文】（支持不对称划分，因为防守安全区和进攻压上区不一定一样宽）：
  - `DANGER_X`：危险区右边界。`ball.x < DANGER_X` → 我方危险区，切防守优先阵型。
  - `ATTACK_X`：进攻区左边界。`ball.x > ATTACK_X` → 对方进攻区，切进攻优先阵型。
  - 两者之间即中间过渡区，保持标准攻守平衡。
  - 参考值：场地 14 m（-7 → +7），初始 `DANGER_X = -2.5`、`ATTACK_X = 2.5`，危险区与进攻区各约占 1/3。
  - 调参：觉得防守不稳 → `DANGER_X` 调大（如 -1.5），危险区变大、更早切防守；想更激进 → `ATTACK_X` 调小（如 1.5），进攻区变大、更早压上。**两个参数至少相差 2 m**，否则球在中线附近来回移动会频繁切换阵型导致抖动。
- **只按 `ball.x` 分区的理由**【原文】：纵向位置决定了"该压上还是该回收"；横向位置有时也有战术价值，但属于进阶（九宫格）。
- **状态机层级**【原文】：把 `Phase.NORMAL` 按区域再做一层细分，即"第二层状态机"；区域分支内部再分角色，共三层：phase → zone → role。
- **进阶方向**【原文】：① 三区扩到五区甚至七区（区域越多切换越频繁、越易抖动）；② 加入 `ball.y` 横向判断做九宫格，边路与中路用不同战术；③ 按比分、剩余时间动态调整 `DANGER_X` / `ATTACK_X`——落后就把进攻区往前推，领先就把危险区扩大加强防守。

## 二、代码与公式

**区域判定（原文"单元2"，三步判断）**

```python
if ball.x < DANGER_X:
    zone = "danger"
elif ball.x > ATTACK_X:
    zone = "attack"
else:
    zone = "middle"
```

**完整三分区 `_act_normal`（原文"单元3"，标明"直接替换 `src/main.py` 中的同名函数即可使用"）**

```python
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

**三个分支的语义（原文逐段拆解）**

| 分支 | 站位/角色公式 | 原文解释 |
|---|---|---|
| `danger`（`ball.x < DANGER_X`） | `attacker = _select_closest_attacker(...)` 后 `attack()`；其余全部 `guard()` | "先保球门，再谈抢球"。这里的 `attacker` 是"去追球的人"而非前锋，追球目的是干扰对方传球和射门，不是带球进攻 |
| `attack`（`ball.x > ATTACK_X`） | `guard = min(players, key=dist to own_goal)`；其余全部 `attack()` | "全力压上，只留一人兜底"。选离我方球门最近的人守门，防止被打反击；2 打 1 的逼抢很容易迫使对方失误 |
| `middle`（其余） | 原版三角：`_select_closest_attacker(..., preferred_id)` → `attack()`；剩余里离己方门最近者 `guard()`；其余 `support()` | 过渡区攻守平衡，不需要极端倾斜；且保留 `normal_attacker` 迟滞机制（防止追球者频繁切换导致抖动） |

**阈值取值表（原文 callout）**

| 参数 | 建议值 | 含义 | 调整效果 |
|---|---|---|---|
| `DANGER_X` | `-2.5`（初始） | 危险区右边界 | 调大（-1.5）→ 危险区变大、更早切防守 |
| `ATTACK_X` | `2.5`（初始） | 进攻区左边界 | 调小（1.5）→ 进攻区变大、更早压上 |
| 两者间距 | `≥ 2.0 m` | 防抖约束 | 太接近会在中线附近频繁切换阵型 |

## 三、易错点与规则红线

- 【原文】分区不能太细：五档、七档会让阵型高频切换，球员抖动、产生混乱。
- 【原文】`DANGER_X` 与 `ATTACK_X` 不要设得太接近，建议至少相差 **2 m**，否则球在中线附近来回移动时会频繁切换阵型。
- 【原文】中间区必须保留 `normal_attacker` 迟滞，否则追球者会随距离排序互换而抖动。
- 【原文】`_act_normal` 开头的 `if not players: return` 不能删——球员全被罚下/未就绪时要有兜底。
- 【原文】区域分支里用"排除法"（`[p for p in players if p is not attacker]`）取剩余人，而不是假设场上恒为 3 人。
- 【经验建议】**原文代码直接 `ball.x` 没有判空**。本项目 `Context.ball` 在约 1.5 s 未更新时为 `None`（AGENTS.md 明确要求"使用前判空"），照抄会 `AttributeError`。必须先 `if ball is None: 退回原版三角/全部 stop`。
- 【经验建议】`danger` 分支两人同时 `guard()` 会走到**同一个** `own_goal_area_center`，本项目 `guard()` 没有横向偏置，两人会互相挤踏。应改成 `guard(lateral=±0.6)` 或一人 `guard()`、一人 `support()`。
- 【经验建议】`attack` 分支两人同时 `attack()` 会争抢同一个球、互相挡路（`attack()` 追球目标点在球后 0.35 m，两人目标几乎重合）。建议改为"最近者 `attack()`、次近者前插到对方禁区前沿做接应"。
- 【经验建议】`store.normal_attacker` 只在 `middle` 分支被更新；从 `attack`/`danger` 切回 `middle` 时会带着过期 id 进入 `_select_closest_attacker(preferred_id)`。虽然 `ATTACKER_KEEP_DIST_MARGIN_M`（0.3 m）限制了影响，但语义上应在每个分支都写 `store.normal_attacker = attacker.id`，或在 zone 变化时清空。
- 【经验建议】zone 切换本身也应加迟滞：记录 `store.normal_zone`，只有越过边界 `ZONE_HYST_M`（建议 0.5 m）才真正换区，避免球贴线时的抖动。

## 四、对本项目的具体改进建议

1. **`src/main.py:228` `_act_normal` 整体重写为三分区版**：保留现有的 `_select_closest_attacker(context, players, preferred_id)` 与 `store.normal_attacker` 迟滞（这块本项目已实现得比原文完整，不要退回去），在其外层套 zone 判定。**开头必须加 `if context.ball is None:` 兜底**——退回当前的三角色基线（`attack`/`guard`/`support`），因为球不可见时无法分区。
2. **`src/main.py:191` `_clear_normal_sticky`**：目前只在非 NORMAL phase 被调用。建议扩展为同时清 `store.normal_zone`，并在 `_act_normal` 内做 zone 边沿检测（zone 变化 → 清 attacker 锁），避免跨区时沿用旧追球者。
3. **`danger` 分支落地写法**：`attacker.attack()` 之后，`rest` 里离己方门最近者 `guard()`，最后一人不要也 `guard()`，改为 `support()`（它天然站在"球 → 己方门"连线上距球 `SUPPORT_DIST_M`=3.0 m 处，正好是禁区前沿的第二道封堵）。这样既满足"2 人防守"又不挤在同一坐标。
4. **`attack` 分支落地写法**：`guard = min(players, key=dist to own_goal)` 后，`rest` 里离球最近者 `attack()`，另一人 `walk_to((field.length/2 - CORNER_RECEIVE_X_M, ±2.0), avoid_ball=True, avoid_robots=True)` 前插接应（与 09 篇的角球接应点复用同一常量，保持体系一致）。
5. **`src/param.py` 新增（当前完全没有这两个常量）**：`DANGER_X = -2.5`、`ATTACK_X = 2.5`、`ZONE_HYST_M = 0.5`、`ATTACK_ZONE_GUARD_Y_M = 2.0`（进攻区前插者的横向站位）、`DANGER_ZONE_SUPPORT_ENABLE = True`（危险区第二人用 support 而非双 guard 的开关）。**注意本项目单位是米、坐标是场地坐标**，`DANGER_X`/`ATTACK_X` 必须是米而不是"分区编号"。
6. **`src/player.py:595` `guard()` 增加 `lateral` 参数**：这是 `danger` 分支"2 人守门"能否成立的前提（见 10 篇同一建议，两篇共用一处改动）。
7. **调参顺序**：先把 `DANGER_X`/`ATTACK_X` 设成 ±2.5 跑一场，看场上标签 `phase=...`（`src/main.py:137` 的 `debugdraw.text`）确认分区切换频率；若一场内 zone 切换超过约 20 次，说明间距不足或需要 `ZONE_HYST_M`。

## 五、原文关键摘录

> **一句话理解分区策略：** 球离我的门近，就要更重视防守；球在对方门口，就应该大胆压上。

> 这种"一刀切"的策略在简单场景下够用，但面对复杂局面就会暴露问题。举个例子：球在我方禁区前，对方球员正准备射门——这时如果还按"离球最近的人去追"，很可能只有一个人在防守，其他人还在前面等着进攻，球门直接暴露给对手。

| 球的位置 | 位置最靠后的球员 | 位置第二靠后的球员 | 位置第三靠后的球员 |
|---|---|---|---|
| 场地前 1/3 | 守门员 | 进攻角色 | 进攻角色 |
| 场地中间 1/3 | 守门员 | 防守角色 | 进攻角色 |
| 场地后 1/3 | 守门员 | 防守角色 | 防守角色 |

> **参数参考值与调参建议：**
> - 场地总长 14m，从 -7 到 +7。初始可以设 `DANGER_X = -2.5`、`ATTACK_X = 2.5`，即危险区和进攻区各约占场地 1/3。
> - **觉得防守不稳？** 把 `DANGER_X` 调大（比如调到 -1.5），危险区范围变大，更早切换防守阵型。
> - **想更激进进攻？** 把 `ATTACK_X` 调小（比如调到 1.5），进攻区范围变大，更早压上进攻。
> - **注意：** 两个参数不要设得太接近，否则球在中线附近来回移动时会频繁切换阵型，导致球员抖动。建议至少相差 2m 以上。
