# v5.0 Spec：把「top 差距三条杠杆」转成可实现规则（离线准备稿）

> 作者：replay-analyst（task-1）。只写文档，不改 src、不跑仿真、不花钱。
> 基线：**v4.5b（当前 1251 分，15 场 13 胜 2 平，credits 0）**；实现由 T1 在 `v5` 分支做（task-2），每步 1–2 处机制。
> 数据来源：`docs/kb/reviews/top-tier-playbook.md`、`top-<队>.md`、`p1.5-counterpress.md`、`v43-00-diagnosis.md`、`v42/v43` 回放。

## 0. 差距与目标（一页）

| 指标（对方三区） | top 均值 | v4.5b 现状 | v5.0 目标 |
|---|---|---|---|
| 触后推进 travel（触球后 1.5 s 球位移） | 2.14 m | 0.75 m | **≥1.20 m** |
| 触后 3 s 内形成射门/向门快球（touch-to-shot） | 16.1% | 3.2% | **≥8%** |
| 禁区触球（box touch/场） | 6–15 | 0–5 | **≥4** |
| 丢球后 3 s 夺回率 / 夺回中位时间 | 70–85% / 0.45–0.65 s | 38–89% / 0.9–1.5 s | **≥60% / ≤0.9 s** |
| 射正/场 | 2.9–7 射 | 0–3 | **≥3** |

三条杠杆（优先级即 Lead 指定）：**P0 前场推进/射门 → P1 禁区终结/第二点 → P1.5 丢球反抢**。三条都必须保留 v4.5b 纪律修复族（R-06/M-02/M-05/预撤/counter 参数）。

---

## 1. 通用前提（三条杠杆共用）

1. **只在 NORMAL 相行动**：`game.state==PLAYING and not game.stopped and (set_play is None or NONE)`；所有定位球/停摆沿用 v4.5b 现逻辑，**不碰**。
2. **球出界/贴线安全**：沿用 `attack()` 的出界判据（`|x|>half_l+0.15`、`|y|>half_w+0.15`）与「球在后侧点必须在场内」的 `_safe_kick_direction` 全局兜底（v4.3 起已在 `src/player.py:206`/kick()）。任何新踢球目标必须同时满足：后侧点场内 + 目标点场内 + 不朝自家门（球在己方半场时）。
3. **不新增「静止」风险**：新规则分配到的球员若 2 s 内无位移且球 >3 m，必须回退到原 support/guard（防 M-05 inactiveRobot）。
4. **状态存储**：沿用 `store.<snake_case>`：`store.last_touch_side`、`store.last_touch_t`、`store.last_touch_pos`、`store.press_until`、`store.front_shot_until`、`store.box2_arrived_t`。Player 内部用 `self._front_ball_prev` 这类实例字段（已有先例）。
5. **一版本只落 1–2 条**：Step1 = A（推进/射门）；Step2 = C（反抢）；Step3 = B（box 终结）。每步独立 A/B，失败可单独回滚。

---

## 2. Lever A（P0）：前场推进 / 射门

### A-1 触发条件（`_coordinated_kick_plan` 前场块，现有 `src/player.py:360-430`）

```
NORMAL && ball is not None && ball.x > 0.0
     && ball_speed < 1.0 m/s            # 现有 FRONT_PUSH_MAX_BALL_SPEED_MPS
     && 触发者 = 当前 attacker（main._select_closest_attacker 已选，不新增角色）
```

### A-2 按距离分区（对方门在 (half_l,0)，d = hypot(half_l-ball.x, ball.y)）

| 区 | 条件 | 行为 |
|---|---|---|
| **Z3 贴线/贴底** | `|ball.y| > half_w-0.30 (=4.20)` 或 `ball.x > half_l-0.60 (=6.40)` | **不射门**；沿长轴推：`target=(clamp(ball.x±1.5, -(half_l-0.3), half_l-0.3), clamp(ball.y,±4.0))`，power 5.0（现有 `KICK_POWER_LINE_CLEAR`）。禁止出界；禁止朝自家门。 |
| **Z1 终结** | 其余且 `d <= 6.5` | 射门：power **9.0**；`aim_abs = goal_half - 0.45 = 0.85`；瞄准「远离门将的一侧」：`aim_y = -sign(keeper.y)*0.85`；若 `|keeper.y|<=0.15` → `aim_y = -sign(ball.y)*0.85`（打远角）；若从 ball→(goal_x-0.15,aim_y) 的直线 1.2 m 内有对手（封堵）→ 改走 Z2 推进。 |
| **Z2 推进** | 其余且 `6.5 < d <= 12.0` | 推进：power **7.0**；`push_x = min(ball.x+2.2, half_l-1.2)`；横向避最近对手 1.2 m（现有）；若最近对手正好在推进方向 1.2 m 内且两侧都被封 → 向**中线侧**斜推 1.2 m（`ball.y→sign(-ball.y)*min(|ball.y|+1.2, half_w-1.2)`）。 |
| **Z2b 距离过远** | `d > 12.0` 但 `ball.x>0` | 朝对方半场边线低平推 pass：power 6.0，target=`(half_l-3.0, sign(-ball.y)*(half_w-1.2))`，仅当该方向无对手 1.5 m 内；否则沿 x 推 2.2 m。 |

### A-3 被挡/失败回退
1. **踢球任务未执行**（1.5 s 内球位移 <0.3 m）：`release_kick()` → 走现有 `attack:wd_*` 看门狗逻辑（3 s 不动会强制处理）；同时 `store.front_shot_until = now+1.0`，避免立刻重复开火。
2. **射门被挡回**（1.2 s 内球速反向且 `ball.x < 4.0`）：attacker 不再追回抢（避免反抢丢位），改为 `action="attack:recover_shape"` → `walk_to((0.5, clamp(ball.y*0.3, ±2)))`；由 P1.5 反抢规则接管第一扑。
3. **贴线球**：A 规则本身不触发射门；若球已出界由 v4.5b 出界/摆球流程接管。

### A-4 A/B 要改的参数（只动这些）
`FRONT_SHOOT_RANGE_M=6.5`（保持不变）、`FRONT_SHOT_POWER=9.0`（不变）、`FRONT_SHOT_INSET_M=0.45`（不变）、`FRONT_PUSH_POWER=7.0`（不变）、`FRONT_SHOOT_LATERAL_MARGIN_M=0.30`（不变）；**新增**：`FRONT_Z2_MAX_DIST_M=12.0`、`FRONT_Z2B_POWER=6.0`、`FRONT_BLOCK_LINE_CLEAR_M=1.2`、`FRONT_SHOT_COOLDOWN_S=1.0`。

---

## 3. Lever B（P1）：禁区终结 / 第二点

### B-1 三类触发（全部仅 NORMAL；box 定义 `ball.x > half_l-3.0 (=4.0)` 且 `|ball.y| < 3.0`）

1. **预置后点（pre-position）**：attacker 进入 `d <= 8.0` 且 `ball.x > half_l-2.5` 时，box2（第二人）站 **后点**：`(half_l-1.4, -sign(ball.y)*0.9)`，移动 speed 1.9 m/s；球到中场以下（`ball.x < half_l-2.5`）→ 取消 box2 回 support（现有取消逻辑）。
2. **补射（rebound）**：球在 box 内且（`ball_speed < 1.0` 或 2 s 内出现过 ≥6 m/s 的射门）且 box2 距球 ≤2.0 m → **omni 直冲球** 1.9 m/s；`d <= 0.55` 时一击：若 ball→goal 线 0.4 m 内无对手 → 射门 power **8.5**、`aim_y=-sign(keeper.y)*0.8`；否则挑角清出：power 5.0 朝 `(half_l-1.0, sign(ball.y)*1.2)`。
3. **倒三角/二过一**：球在边路区（`4.0 < ball.x < 6.2` 且 `1.0 < |ball.y| < 3.0`）且有禁区接应者（`x>5.0 && |y|<1.8`）→ 传球 power **6.5** 到 `(half_l-1.9, 0)`；传球者传后前插到 `(half_l-1.4, sign(ball.y)*0.9)`；接应者若球速 ≥3 且距球 ≤1.0 → 一脚射近角 power 8.5、`aim_y=sign(ball.y)*0.55`（现有 `CROSS_*` 参数已覆盖落点/近角，v4.5b 已实现「有接应→倒三角、无接应→近角」；B 新增的是「接应者一脚终结」与「box2 预置后点」）。

### B-2 边界
- **同一时间最多 1 名非门将进 box**；其余保持 rest defense：`x ≈ 0.0 ± 0.5`、沿 ball→own-goal 线。
- box2 **不得由 keeper 担任**；box2 到位后 2 s 未触球且球离开 box → 回 `(0.5, clamp(ball.y,±2))`。
- 传球被断：不做反抢第一人（由 C 规则指派），回 rest defense。

### B-3 参数
沿用 `CROSS_PULLBACK_X_FROM_GOAL=1.9`、`CROSS_PULLBACK_POWER=6.5`、`CROSS_NEAR_POST_AIM_Y=0.55`、`BOX_CRASH_X_FROM_GOAL=1.4`、`BOX_CRASH_Y=0.9`；**新增**：`BOX2_SPOT_X_FROM_GOAL=1.4`、`BOX2_SPOT_Y=0.9`、`BOX2_SPEED=1.9`、`BOX2_CRASH_R=2.0`、`BOX2_CONTACT_M=0.55`、`BOX2_SHOT_POWER=8.5`、`BOX2_CLEAR_POWER=5.0`、`BOX2_MAX_IN_BOX=1`。

---

## 4. Lever C（P1.5）：丢球即反抢

### C-1 丢球事件检测（新增，建议在 `main.play()` 的 `_act_normal` 前）
```
每帧差分球速 = |ball.pos - prev_ball.pos| / dt
if 球速跃升 > 1.5 m/s:
    side = home if 最近 home 距球 <=0.75 else away
    if side=='away' and store.last_touch_side=='home':
        store.loss_t = now; store.loss_pos = ball; store.press_until = now + 2.5
    store.last_touch_side = side; store.last_touch_t = now
```
`_act_normal` 中当 `now < store.press_until` 且 `ball.x <= 2.0`（球不在对方三区）时，从 `field_players`（已排除 keeper）选 2 人：

| 角色 | 选择 | 行为 |
|---|---|---|
| **P1 第一扑** | 距球最近 | `omni_move_toward(ball, 1.8 m/s)`（**不绕球后方**）；`d<=0.55` 时 `kick(power 5.0, target=(clamp(ball.x-1.5), sign(ball.y)*(half_w-0.8)))` 朝我方半场边线解围；最多 2.0 s，之后回 support。 |
| **P2 封内线** | 次近 | 目标=`ball + 1.2·unit(own_goal-ball)`（球与门之间），speed 1.8；到位后 `stop()` 站位封直塞/补 P1 身后。 |
| **P3 占门线侧** | 第三近（若 3 台可动） | 目标=`ball + 2.5·unit(own_goal-ball)`，clamp x≥-(half_l-2.5)；speed 1.6。 |
| **keeper** | 不参与 | 保持 `guard(ball_vel)`；仅当球进本方禁区且最新防守者>0.8 m 才 clear power 6.5。 |

### C-2 夺回后第一脚（关键：防「抢而不下」/倒脚）
- 球权回到我们（`last_touch_side` 变 home 且 `now - last_recovery < 1.0`）：**禁止 slowball:approach 慢速倒脚**；第一脚 power ≥5.5：
  - 球在己方半场 → 朝对方半场边线解围 power 6.5（现有 `attack:clear` 已符合）；
  - 球在中前场 → 按 Lever A：`d<=6.5` 射门 9.0，否则推进 7.0。
- 实现：`store.recover_until = now + 1.0`；`slow_ball_since` 在 `recover_until` 内重置为 None（不让 slowball 抢走第一脚）。

### C-3 边界
- **定位球/停摆期间绝不反抢**（`set_play≠NONE or stopped` → 不进入 C）。
- 球在对方三区（`ball.x>3.0`）不启动反抢：改为 2 人回 rest shape，防被反击（v4.2 #58 反击失球教训）。
- 反抢总时长 ≤2.5 s；超时全员回位。

### C-4 参数
`PRESS_ON_LOSS_WINDOW_S=2.5`、`PRESS_MAX_LOSS_BALL_X=2.0`、`PRESS_FIRST_SPEED=1.8`、`PRESS_FIRST_CONTACT_M=0.55`、`PRESS_FIRST_POWER=5.0`、`PRESS_BLOCK_D=1.2`、`PRESS_BLOCK_SPEED=1.8`、`PRESS_LANE_D=2.5`、`PRESS_LANE_SPEED=1.6`、`PRESS_DURATION_S=2.0`、`PRESS_KEEPER_CLEAR_POWER=6.5`、`RECOVER_FIRST_TOUCH_POWER=5.5`、`RECOVER_WINDOW_S=1.0`。

---

## 5. 验收指标（全部可从回放离线计算）

### 5.1 指标定义
1. **progression travel**：对方三区（`ball.x>4.0` 或按进攻方向 x>0 且过半场）我方触球后 1.5 s 球位移的中位/均值（`top_analyze2.py` 的 zone/`zone_events.py` 已给 avg_travel；复用同一函数）。
2. **touch-to-shot%**：对方三区我方触球中，触后 3 s 内出现「球速≥3.5 m/s 且朝对方门」的射门/快球的占比（`top_analyze2.py::shots` + `zone_events.py::shot_share`）。
3. **box touch**：球在对方禁区（`ball.x>half_l-3.0, |y|<3.0`）且我方某球员距球≤0.7 m，去重（≥2 s 记一次）的段数/场（`box_metrics.py`）。
4. **box touch→shot**：box touch 后 2 s 内形成射门的比例（`box_metrics.py` + shots 时间序列）。
5. **recovery**：我方触球→对方触球（失球）后，到下一次我方触球的间隔；统计 ≤3 s 的比例与中位；对方 3 s 内触球次数（新脚本 `press_loss.py`，按第 4 节事件定义）。
6. **射正/场、goals/shot**：rep.json 的 `shots`（on_target）+ `goals`（`analyze2.py` 口径）。
7. **纪律**：R-06/R-07/M-02/fallen/inactive/global_game_stuck 事件数（manifest events + analysis.json）。

### 5.2 通过阈值（v5.0 相对 v4.5b）

| 指标 | 阈值 | 判定 |
|---|---|---|
| progression travel（对方三区触后 1.5 s） | ≥1.20 m（基线 0.75） | 主 |
| touch-to-shot% | ≥8%（基线 3.2） | 主 |
| box touch/场 | ≥4 | 主 |
| recovery ≤3 s 比例 / 中位 | ≥60% / ≤0.9 s | 主（反抢） |
| 射正/场 | ≥3 | 次 |
| goals/shot | ≥0.15 | 次 |
| **纪律红线** | R-06=0、R-07=0、M-02=0、inactive=0、fallen=0、global_stuck=0 | **必须** |
| 防守不回归 | 失球 ≤ 对手同段位场均；`ball 己方半场占比 ≤45%`；oobCaused ≤15/场 | **必须** |

## 6. 4 场小样本 A/B（v5.0 vs v4.5b）

### 6.1 设计（同对手/同段位配对，控制强度）
- **对手池**（1050–1300 段，来自 `rematch_targets.json`）：`0707`（1055，活跃）、`张原硕`（1076，历史 0:0×3，专测推进破密集）、备选 `瘤子牢孟`(1101)、`如果以后`(1005→略低于段位，备用)。
- **配对**：Pair1 = 0707：先 v4.5b 一场、30 min 内 v5 一场；Pair2 = 张原硕：同样一控一测。若同一对手第二次邀不到 → 用同段位 ±50 的同等级对手替换，并在报告中标注「非严格配对」。
- **执行约束**：一次只开 1 场（并发场次平台有 initial 20–50 s、球出界不重启的抖动，已多次污染样本）；两场间隔 ≤30 min，减少平台漂移；同一天、同一 arena。
- **样本判定**：4 场 = 2 控制（v4.5b）+ 2 实验（v5.0）。

### 6.2 通过标准
1. **主指标**：4 个主指标里 **≥2 个达到 §5.2 阈值**，且没有任何主指标比控制组差 >20%；
2. **纪律红线**：v5 两场全部 0 违规（R-06/R-07/M-02/inactive/fallen/stuck）；
3. **结果不回归**：v5 两场积分（W=3/D=1/L=0）≥ 控制场积分；或积分持平但主指标 ≥2 项显著改善（按样本量只作方向判断，不追求统计显著）；
4. 任一红线失败 → 回滚该机制，不进入 12 场扩展。

### 6.3 credits 预估（当前 0，恢复后用）
- 单机制 4 场 A/B：**4×10 = 40 credits**；三机制串行共 **120 credits**（+ 10 缓冲 = 130）。
- 通过后的 12 场扩展验证（混合 1050–1300 对手）：**120 credits**。
- 全程 v5.0 A/B 预算：**250 credits 以内**；若只做 P0+P1.5 两条：**~170 credits**。

---

## 7. 实现顺序与 T1 接口（task-2）

| Step | 机制 | 改动文件/位置 | 验收 |
|---|---|---|---|
| 1 | Lever A（§2） | `src/player.py::_coordinated_kick_plan` 前场块（现 360–430 行）；`src/param.py` v5 段（新增 4 个参数） | 4 场 A/B；progression travel / touch-to-shot |
| 2 | Lever C（§4） | `src/main.py::_act_normal` 前置事件检测 + 角色指派（新函数 `_assign_counterpress`）；`src/player.py` 新增 `press_direct/block_inside/lane_cover` 三个轻量动作 | 4 场 A/B；recovery rate |
| 3 | Lever B（§3） | `src/main.py` box2 块（现 874–899 行）；`src/player.py` 新增 `one_touch_finish` | 4 场 A/B；box touch / box→shot |
- 每步：`py_compile` + `python3 tools/static_check.py` + `python3 tools/replay_playcheck.py`（最近 30 场 0 异常）→ 离线 build 候选 `.agent`（记录 sha256/大小/commit），**不 POST /3v3/codes、不下单**。
- 每步独立 commit（`v5-step1: ...`），便于单独回滚；`docs/kb/online-loop.md` 的「v5.0 候选」段由 T1 更新。
- 所有新参数集中在 `src/param.py` v5 段并带注释；不复用 v4.x 同名参数，避免 A/B 混淆。

## 8. 风险与回滚

| 风险 | 触发场景 | 缓解 |
|---|---|---|
| R-07/R-06 回归 | 反抢/box2 在对方定位球摆球期靠近 | C 规则 `set_play!=NONE or stopped` 直接禁用；box2 只在 NORMAL |
| M-05 inactive | box2 在禁区角等球 10 s | box2 到位 2 s 未触球且球离开 box → 回 rest；每个新角色 2 s 无位移回退 |
| oobCaused 升高 | 前场射门偏出（近门柱） | 只射 Z1 且 `|ball.y|<4.2`；瞄点 inset 0.45，不瞄边线 |
| 后场空档被反击 | 反抢把 2 人抬到中场 | 反抢上限 2 人（P3 只在球 x≤0 时启用）；球在对方三区不反抢 |
| 规则上限（开球/定位球二次触球） | 新 kick 参数不碰开球/定位球分支 | A/B/C 只在 NORMAL 生效 |
**回滚**：每步单独 commit；任一红线失败 → `git revert` 该 step，保留其它已通过步骤。

---

## 9. 一页参数表（新增，v5 段）

```python
# Lever A
FRONT_Z2_MAX_DIST_M = 12.0
FRONT_Z2B_POWER = 6.0
FRONT_BLOCK_LINE_CLEAR_M = 1.2
FRONT_SHOT_COOLDOWN_S = 1.0
# Lever B
BOX2_SPOT_X_FROM_GOAL = 1.4
BOX2_SPOT_Y = 0.9
BOX2_SPEED = 1.9
BOX2_CRASH_R = 2.0
BOX2_CONTACT_M = 0.55
BOX2_SHOT_POWER = 8.5
BOX2_CLEAR_POWER = 5.0
BOX2_MAX_IN_BOX = 1
# Lever C
PRESS_ON_LOSS_WINDOW_S = 2.5
PRESS_MAX_LOSS_BALL_X = 2.0
PRESS_FIRST_SPEED = 1.8
PRESS_FIRST_CONTACT_M = 0.55
PRESS_FIRST_POWER = 5.0
PRESS_BLOCK_D = 1.2
PRESS_BLOCK_SPEED = 1.8
PRESS_LANE_D = 2.5
PRESS_LANE_SPEED = 1.6
PRESS_DURATION_S = 2.0
PRESS_KEEPER_CLEAR_POWER = 6.5
RECOVER_FIRST_TOUCH_POWER = 5.5
RECOVER_WINDOW_S = 1.0
```

## 10. 复跑命令（离线验收）
```bash
# 单场全量
python3 /tmp/ra/analyze2.py <uuid> --out /tmp/ra/v5/<short>.rep.json > /tmp/ra/v5/<short>.rep.txt
python3 /tmp/ra/top_analyze2.py <uuid> --focus Robot妙妙屋 --out /tmp/ra/v5/<short>.pb.json
python3 /tmp/ra/zone_events.py <uuid> Robot妙妙屋 > /tmp/ra/v5/<short>.zone.txt
python3 /tmp/ra/box_metrics.py <uuid> Robot妙妙屋 > /tmp/ra/v5/<short>.box.txt
# 新增（本 spec 配套，需实现）：
#   /tmp/ra/press_loss.py <uuid> Robot妙妙屋   # 丢球事件/3 s 夺回/对方触球数
#   /tmp/ra/v5accept.py <uuid...> --ctrl <uuid...>  # 汇总 §5 表 + 配对对比
```
