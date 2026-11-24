# 风格 B（硬踢长球 + 贴线门将）参数/行为落地规范

> 样本：WR（rank3，2020-11-24 rating 2014）两场 `5d8b77c0`（home 2:2 从模仿到超越）、`8c7af7c2`（away 4:0 彩雨伞）。对照：官网（控制型）`ddb93eec`、克利夫兰（均力型）`01cb5600`、我们 `11f01b49`/`b0a2afea`。
> 数据脚本（可复跑）：`/tmp/ra/styleB.py <uuid> <focus> --out <json>`（踢球 session 的力度/三区/落点、门将线深、丢球后 1/2 s 人数与接近速度）；`/tmp/ra/strikes.py <uuid> <focus> --out <json>`（**真实起脚**：球速跃升 ≥4 m/s 且最近同侧机器人 ≤0.85 m，取该帧 kick.power；输出起脚位置/力度/1.2 s 后落点/是否到对方半场/边路/出界）。
> 产出文件：`/tmp/ra/styleB/styleB_*.json`、`/tmp/ra/styleB/strikes_*.json`、`/tmp/ra/loss/*.json`。

## 1. 核心事实（帧级证据）

### 1.1 踢球力度分布（真实起脚，power 来自 commandIntents.kick.power）
| 队伍/场次 | 己方三区 | 中三区 | 对方三区 |
|---|---|---|---|
| WR `5d8b77c0` | n=14, p50 **9.7**, 球速中位 6.2 m/s，travel 中位 5.5 m | n=9, p50 **9.4**, 7.1 m | n=6, p50 7.3, 5.7 m |
| WR `8c7af7c2` | n=6, p50 **9.4**, travel **9.4 m** | n=2, p50 9.4, 7.6 m | n=16, p50 **6.0**, travel 2.5 m |
| 官网（对照） | n=8, p50 5.1, travel 2.5 m | n=9, p50 5.1, 6.5 m | n=10, p50 6.0, 4.2 m |
| 克利夫兰（对照） | n=25, p50 6.0, travel 8.4 m | n=21, p50 5.1, 7.0 m | n=4, p50 6.0, 8.3 m |
| 我们 `11f01b49` | n=3, p50 **4.5**, travel **1.4 m** | — | n=3, p50 7.2, 7.2 m |
| 我们 `b0a2afea` | n=5, p50 6.5, travel 7.4 m | n=3, p50 5.6, 2.2 m | n=2, p50 6.5, 6.8 m |

WR 的 power band（全部 session）：`5d8b77c0` hard(≥8) **68%**（9+ 占 61%，<4 仅 7%）；`8c7af7c2` hard 33%（9+ 占 33%）。→ **WR 在己方/中三区几乎只用 9.4–9.7 的硬踢，只有在对方三区才降到 6–7.3**。

### 1.2 长球落点（起脚后 1.2 s 球位）
| 队伍/场次 | 己方三区起脚：到对方半场 | 边路 | 出界 | 中三区起脚：到对方半场 | 边路 | 出界 |
|---|---|---|---|---|---|---|
| WR `5d8b77c0` | 4/14 (29%) | 5/14 | 4/14 | **9/9 (100%)** | 2/9 | 4/9 |
| WR `8c7af7c2` | 6/6 (100%) | 2/6 | 1/6 | 2/2 | 1/2 | 1/2 |
| 官网 | 0/8 | 3/8 | 2/8 | 4/9 | 4/9 | 3/9 |
| 克利夫兰 | 15/25 (60%) | 3/25 | 2/25 | 10/21 | 11/21 | 5/21 |
| 我们 `11f01b49` | **0/3** | 2/3 | 2/3 | — | — | — |
| 我们 `b0a2afea` | 5/5 | 3/5 | 1/5 | 3/3 | 0/3 | 0/3 |

→ 顶级长球不是「盲目远射」：**中三区起脚 100% 过中线、落点偏向对方半场肋部/边路**；己方三区硬踢目标 = 对方半场边路（WR 29–100% 过半），允许 29% 出界（对方界外球在远处，可接受）。

### 1.3 门将
| 队伍/场次 | 线深中位（距本方门线） | y_std | 固定门将占比 | advanced(>2 m) |
|---|---|---|---|---|
| WR `5d8b77c0` | **0.54 m** | 0.72 | 89% | 0% |
| WR `8c7af7c2` | **0.18 m** | 0.63 | 98% | 0% |
| 官网（对照） | 2.22 m（中卫位） | 1.61 | 65% | 61% |
| 我们 `11f01b49` | 0.33 m | 1.16 | 98% | 0% |

→ WR 门将**贴门线且横向稳定**（y 标准差 0.6–0.7，远小于我们 1.16）；对照官网是「门将前提到中卫位」的另一极端。

### 1.4 丢球后反应（3 s，来自 `/tmp/ra/loss3s.py`，我方半场丢球样本）
| 队伍 | 己方半场丢球 n/场 | 3s 内夺回率 | 夺回中位 | +1s 内 3m 内人数 | 3s 内对方触球数 | 3s 球移动 |
|---|---|---|---|---|---|---|
| WR `5d8b77c0` | 10 | 70% | 0.65 s | 2.00 | 1.32 | 3.73 m |
| WR `8c7af7c2` | 13 | **85%** | **0.45 s** | **2.62** | 0.93 | 2.75 m |
| 官网 `ddb93eec` | 16 | 50% | 0.79 s | 1.62 | 0.83 | 4.21 m |
| 我们 `08ac7eb6` | 9 | 89% | 0.92 s | 2.33 | 1.56 | 2.85 m |
| 我们 `11f01b49` | 8 | 38% | 0.66 s | 1.62 | **1.91** | 3.15 m |
| 我们 `b0a2afea` | 2 | 50% | 0.83 s | 1.50 | 0.61 | 6.69 m |

→ 我们丢球后的**人数不少**（1.5–2.3），但 `11f01b49` 对方 3 s 内触球 **1.91 次（最高）**、夺回率仅 38%：**抢而不下**。WR 8c7af7c2 的 2.62 人围抢 + 0.93 次对方触球 + 85% 夺回是目标形态。

### 1.5 禁区存在（box 指标，`/tmp/ra/box_metrics.py`）
- WR `8c7af7c2`（4:0）：ball 在对方禁区 **2863 帧（全场 50%）**、box touch 10；`5d8b77c0`（2:2）：1595 帧、box touch 9。
- 官网 756–1106 帧、克利夫兰 834–1578 帧；我们 157–728 帧、box touch 0–4。

## 2. 风格 B 参数集（建议写入 `src/param.py`，命名与 v4.0a 分离）

```python
# ---- 风格 B：硬踢长球 + 贴线门将 ----
STYLE_B = True
B_CLEAR_POWER = 9.4            # 己方三区解围/长球
B_MID_PUSH_POWER = 9.4         # 中三区向前的穿透球
B_FINAL_POWER = 7.0            # 对方三区短促推进/射门前的最后一脚
B_SHOT_POWER = 9.4             # 禁区/距门≤7m 射门
B_CLEAR_MIN_DIST_M = 4.5       # 己方三区起脚后 1.2s 期望移动（验收）
B_OWN_HALF_TARGET_Y = 2.6      # 长球目标边路 |y|（对方半场肋部）
B_MID_TARGET_X = 6.0           # 中三区长球目标 x_att
B_KEEPER_DEPTH_M = 0.35        # 门将离门线目标深度（0.2–0.5）
B_KEEPER_Y_GAIN = 0.85         # 门将跟球横移增益
B_KEEPER_Y_LIMIT = 1.15        # 门将横移幅度限制
B_PRESS_RADIUS_M = 2.5         # 第二人围抢半径
B_PRESS_SPEED_MPS = 1.8        # 第一人扑球速度
B_PRESS_DURATION_S = 2.0       # 扑球持续（球未出己方三区则继续）
B_GOALSIDE_GAP_M = 2.5         # 最深球员保持球→己门线侧的距离
```

### 2.1 行为规则（伪代码级，可直接映射到 main.py/player.py 分支）

```python
# A. 有球（进攻）
def styleB_attack(ball, nearest, zone):
    if zone == "own" and nearest.d < 0.8:
        target = (att_x=+3.5, y=sign(ball.y)*B_OWN_HALF_TARGET_Y)   # 对方半场边路
        nearest.kick(toward(target), power=B_CLEAR_POWER)            # 硬踢，不绕后
    elif zone == "mid" and nearest.d < 0.8:
        target = (att_x=B_MID_TARGET_X, y=opposite_side_of_nearest_opponent(ball))
        nearest.kick(toward(target), power=B_MID_PUSH_POWER)         # 穿透球，100% 过中线
    elif zone == "opp" and nearest.d < 0.8:
        if in_box(ball) or dist_goal(ball) < 9.0:
            nearest.kick(far_post(ball), power=B_SHOT_POWER)         # 远角射门
        else:
            nearest.kick(toward(box_corner(ball)), power=B_FINAL_POWER)  # 6–7.3 轻推入禁区
# B. 无球（丢球后 3 s）
def styleB_press(ball, our_players, keeper):
    if ball_zone in ("own", "mid"):
        p1 = nearest_non_keeper(ball); p2 = second_nearest(ball); p3 = deepest_non_keeper
        p1.omni_toward(ball, speed=B_PRESS_SPEED_MPS)        # 0.3 s 内启动，2 s 内持续
        p2.omni_toward(ball + 0.6*unit(ball - p2), speed=B_PRESS_SPEED_MPS)  # 封内线
        p3.hold(goal_side_point(ball, our_goal, gap=B_GOALSIDE_GAP_M))       # 只一人回收
        keeper.hold_line(depth=B_KEEPER_DEPTH_M, y=clamp(B_KEEPER_Y_GAIN*ball.y, ±B_KEEPER_Y_LIMIT))
    else:  # 对方三区丢球：立即 2 人反抢，1 人回中线
        p1, p2 = nearest_two(ball)
        p1.omni_toward(ball, B_PRESS_SPEED_MPS); p2.omni_toward(ball_support_side(ball), 1.6)
        deepest.hold(midline_support_point(ball))
# C. 门将（风格 B 覆盖 v4.0a 门将参数）
keeper.line_depth_target = B_KEEPER_DEPTH_M        # 0.2–0.5 m
keeper.y_gain = B_KEEPER_Y_GAIN; keeper.y_limit = B_KEEPER_Y_LIMIT   # 横向稳定，y_std ≤0.7
keeper.never_advance = True                        # advanced_share = 0
```

### 2.2 与 v4.0a（控制型）的 A/B 对照设计

| 项 | A 组：v4.0a 控制型（P0 前场推进/射门） | B 组：风格 B（本 spec） |
|---|---|---|
| 踢球力度 p50 | 6.0 | 9.4（己方/中三区），对方三区 6–7.3 |
| hard(≥8) 占比 | <10% | 己方/中三区 ≥50% |
| 长球（1.5 s 移动 ≥6 m）占比 | 6–8% | ≥25% |
| 门将线深 | 1.2–1.5 m（高位扫荡） | 0.2–0.5 m（贴线） |
| 落点策略 | 短传/推进到对方三区 | 中三区穿透到对方半场边路 + 禁区混战 |
| 反抢 | 就近 1 人抢，第二人回位 | 2 人围抢（半径 2.5 m，第一人 1.8 m/s，持续 2 s） |
| 样本量 | 3 场 | 3 场（同对手池、同地图） |

**AB 选型判据（验收见 §3）**：先看「球过半场率 + box 帧 + 失球」三个维度；若 B 组 box 帧 ≥A 组 1.5× 且失球 ≤A 组 +0.5/场，则选 B（或 A 的 p50 提到 7.0 的中间形态）；若 B 组 oob caused > A 组 50% 或 R-06/R-07 增加，则 B 降级为「只保留门将贴线 + 己方三区硬解围」子集。

## 3. 验收口径（沿用 playbook §6，加 B 组专属项）

每场跑 `strikes.py` + `loss3s.py` + `box_metrics.py` + `zone_events.py`，两组各 3 场取均值：
- 通用（playbook §6）：box touch ≥4/场、box 帧 ≥700、对方三区 shot_share ≥10%、travel_med ≥1.2 m、shots ≥4、进球 ≥1.2/场、ball 己方半场 ≤45%、0 R-06/R-07/M-02、global_game_stuck=0。
- 风格 B 专属：己方三区起脚后 1.2 s 移动中位 ≥4.5 m、到对方半场比例 ≥25%；中三区起脚到对方半场 ≥60%；门将线深中位 0.2–0.5 m、y_std ≤0.8、advanced=0；丢球后 3 s 内夺回率 ≥60%、夺回中位 ≤0.9 s、对方 3 s 触球 ≤1.2 次。

## 4. 风险与回退
- 硬踢 9.4 在己方三区有 29% 直接出界 → 对方界外球在远处可接受，但会增加 oob caused；若 oob caused > 20/场，目标点内收 0.3 m。
- 2 人围抢 + 门将贴线使身后空间大：遇到长传反击型对手先 A/B 各 3 场；若被反击失球 ≥2/场，第二人改为「封传球线」而非扑球。
- 门将贴线要求后侧不被绕过：keeper y_limit 1.15 是 R-07 豁免线（站门线 y≤1.35）内，安全。
