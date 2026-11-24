# 门将过线点预测 + P0-1 门控 可实现规格（v4.0b P0）

> 作者：replay-analyst；日期：2026-11-24；状态：**编码规格（T1 落地用）**
> 依据：v3.3d #49/#50/#51、v4.0a #52/#53 共 6 个慢球失球（2.11–6.83 m/s、球走 1.5–4.8 s）+ 2 个门线乌龙（v3.3d #49、v4.0a #53）帧级复核。
> 目标：门将按**预测过线点**横移，而不是当前 `ball.y`；P0-1 撤位只在「球将出界且不在我方门线方向」时触发。

## 1. 现状（代码事实，勿重复踩）

- `src/player.py::guard()`（约 1063 行起）：
  - `home = (-(half_l - KEEPER_LINE_INSET_M), …)`，`KEEPER_LINE_INSET_M=0.2` → 门将贴线 x≈−6.8（正确）；
  - 球在己方半场（`ball.x < 0`）：`cover_y = clamp(ball.y * 1.0, -1.15, +1.15)` —— **只跟当前球 y，无任何预测**；
  - 球在对方半场：`cover_gain=0.5 / limit=0.8`（保守跟随，保留）；
  - 解围：`d_ball < KEEPER_CLEAR_RADIUS_M(1.35)` 且 open_play → `guard:clear`（保留，Lead 要求「球进 1.35m 内直接解围」已由该参数满足）；
  - 移动：`self.walk_to(home, face=face, avoid_ball=False, avoid_robots=True)`。
- 球速工具：`src/main.py::_ball_velocity_mps(context, store)` 用上一帧差分，**每帧只能算一次**（重复调用会把 `store.ball_prev` 覆盖成本帧、dt≈0 返回 None）。`_act_normal` 里已有 `ball_vel = _ball_velocity_mps(context, store)`（约 566 行）可直接传。
- v4.0a 证据：`_act_normal` 的 P0-1 在 `ball.x < -(half_l−margin)` 且 `vx<−min_v` 时也会触发——#52 769 它把门前最近的 robot1 从 (−6.41,1.76) 撤走、#53 442 把 robot2 从门线前拉走，两球随后直接进网。

## 2. 接口与数据流（最小 diff）

1. `src/main.py::_ball_velocity_mps` 加「同帧缓存」：`if getattr(store,"ball_vel_t",None)==context.now: return getattr(store,"ball_vel",None)`，算完后写 `store.ball_vel`/`store.ball_vel_t`。这样多处调用安全。
2. `Player.guard(self, ball_vel=None)`：新增可选参数；guard 内用 `ball_vel` 做预测，None 时回退旧逻辑。
3. 调用点（`src/main.py` 830/893/982/1134/1203 五处）统一改为 `keeper.guard(ball_vel=...)`：能拿到本帧 `ball_vel` 的直接传；否则传 `_ball_velocity_mps(context, store)`（有了同帧缓存不会重复消耗）。
4. 不改 `play()` 签名、不新增线程/网络/磁盘 IO。

## 3. 伪代码（≤40 行，可直接落地）

```python
# ---- src/param.py 新增 ----
KEEPER_PRED_MIN_SPEED_MPS = 0.30   # 只有朝我方门滚得比这快才预测
KEEPER_PRED_MAX_T_S       = 4.0    # 光行时>4s 不追(预测越远越不可靠)
KEEPER_PRED_MARGIN_M      = 0.25   # 预测点收进门柱内 0.25m
KEEPER_TRACK_SPEED_MPS    = 1.60   # 门将横移速度上限
KEEPER_TRACK_DEADBAND_M   = 0.10   # 目标变化小于此值不重设,防抖

# ---- src/player.py::guard() 内替换"球在己方半场"分支 ----
def _predict_cover_y(self, ball, ball_vel) -> float:
    half_l   = self.context.field.length / 2.0
    goal_half= self.context.field.goal_width / 2.0          # 1.3
    y_lim    = goal_half - KEEPER_PRED_MARGIN_M             # 1.05
    follow   = clamp(ball.y, -y_lim, y_lim)                 # 回退:跟随当前球 y
    if ball_vel is None:
        return follow
    vx, vy = ball_vel
    if vx >= -KEEPER_PRED_MIN_SPEED_MPS:                    # 不朝门/太慢 → 回退
        return follow
    t = (ball.x + half_l) / (-vx)                           # 到门线的光行时
    if t <= 0.0 or t > KEEPER_PRED_MAX_T_S:                 # 已过线/太远 → 回退
        return follow
    pred = ball.y + vy * t
    return clamp(pred, -y_lim, y_lim)                       # 预测出界则守门柱

# guard() 内:
#   if ball is not None:
#       if ball.x < 0.0:
#           cover_y = self._predict_cover_y(ball, ball_vel)
#           home = (-(half_l - KEEPER_LINE_INSET_M), cover_y)
#       else:  # 对方半场:保持旧保守跟随
#           cover_y = clamp(ball.y * 0.5, -0.8, 0.8); home = (home[0], cover_y)
#   # 防抖:目标变化 < deadband 时沿用上一帧目标
#   prev = getattr(self, "_guard_cover_y", None)
#   if prev is not None and abs(home[1] - prev) < KEEPER_TRACK_DEADBAND_M:
#       home = (home[0], prev)
#   self._guard_cover_y = home[1]
#   # 移动:横向差>0.15m 时用全向横移(不先转身),否则 walk_to 原位微调
#   if abs(self.pose.y - home[1]) > 0.15:
#       face = angle_to(self.pose.x, self.pose.y, ball.x, ball.y)
#       self.action = "guard:home"
#       self.omni_move_toward(home, speed=KEEPER_TRACK_SPEED_MPS)
#       return
#   self.action = "guard:home"; self.walk_to(home, face=face, avoid_ball=False, avoid_robots=True)
```

## 4. 边界条件（必须覆盖）

| 条件 | 处理 |
|---|---|
| 帧率/回放 10 Hz vs 线 ~30 Hz | `_ball_velocity_mps` 已用 `context.now` 差分；dt>0.5 或 ≤1e-3 返回 None → 回退跟随 |
| 球被裁判传送/摆球（单帧位移 >2 m） | 预测输入不可信：在 `_ball_velocity_mps` 里若单帧位移 >2.0 m 返回 None（建议加一行） |
| 球速<0.3 或远离（vx≥−0.3） | 回退 `clamp(ball.y, ±1.05)` 跟随 |
| 光行时 0<t≤4 s | 压预测点；>4 s 不追（避免远球过冲、被挑传身后） |
| 预测点 |pred_y|>1.3 | clamp 到 ±1.05，守门柱 |
| 球距门 1.35 m 内、open_play | 先走 `guard:clear`（现状保留，优先于预测） |
| 球在对方半场 | 保留 0.5/0.8 保守跟随，不启用预测 |
| 门将 x | 固定 `-(half_l-KEEPER_LINE_INSET_M)`；只要出现 `self.pose.x < -(half_l-KEEPER_LINE_INSET_M)-0.1` 立刻向场内走（防 #53 的 x=−7.11 站线外） |

## 5. P0-1 撤位门控（两处判定 + 验收测试点）

**判定 1：方向门控——球朝我方门时不撤，改为封线。**
在 `_act_normal` 的 `going_out` 计算后加两道否决：
```python
own_goal_dir = (own_goal.x - ball.x, own_goal.y - ball.y)      # 球→己门
incoming = (ball_vel[0]*own_goal_dir[0] + ball_vel[1]*own_goal_dir[1]) > 0 \
           and ball.x < 0.0
if incoming:                     # 球朝我方门滚动 → 不是"将出界",禁止 P0-1
    going_out = False
if ball.x < -2.0:                # 球已在我方三区 → 交给 guard:clear/line_clear
    going_out = False
```
**判定 2：目标点门控——撤位目标必须「远离我方门、且在场内」。**
```python
ux_o, uy_o = own_goal.x - ball.x, own_goal.y - ball.y
un = hypot(ux_o, uy_o)
tx, ty = ball.x + 2.4*ux_o/un, ball.y + 2.4*uy_o/un
if tx < -(half_l - 1.2): tx = -(half_l - 1.2)     # 离己方门线至少 1.2m
if tx < ball.x + 0.5 and ball.x < 0:               # 不能比我方门更靠后
    tx, ty = ball.x, ball.y + (2.4 if ball.y >= 0 else -2.4)  # 改横向撤
```
另外：撤位执行前先退旧 kick 任务（`p.release_kick()`），避免"边踢边撤"。

**验收测试点（T1 改完、我按 2–3 场归档验证；每项独立可测）**

| # | 测试点 | 判定式（帧级/事件级） | 通过线 |
|---|---|---|---|
| A1 | 慢球失球 | 丢球前 3 s 球速 <4 m/s 且无折射/乌龙 | 2 场 **0** |
| A2 | 门将过线点误差 | 对球朝门且 vx<−0.3 的帧，取过线时刻 `|keeper_y − pred_y|` | 中位 **≤0.35 m**，最大 ≤0.6 m |
| A3 | 门将横移响应 | 预测目标与当前 y 差 >0.3 m 时，门将横向速度 ≥0.3 m/s 的帧占比 | **≥60%** |
| B1 | P0-1 触发放错区 | `normal:out_retreat` 帧中 `ball.x<−2.0` 或球朝己门（点积>0）的帧数 | **0** |
| B2 | P0-1 目标越界/靠后 | `out_retreat` 目标的 x < −(half_l−1.2) 或比我方门更靠后的次数 | **0** |
| C1 | R-06 | `defender_set_play_interference` / `defender_touched_before_kick` 罚单 | 2–3 场 **0** |
| C2 | 贴线活球无人触 | 球距线 <0.30 m、球速<0.5、最近我方 >0.6 m，持续 >3 s 的段数 | **0** |
| D1 | 射正/box | 我方射正 ≥3/场；对方禁区 box touch ≥4/场（playbook §6） | 达到 |
| D2 | 纪律回归 | M-02 / R-07 / fallenRobot / inactiveRobot | 全 **0** |

## 6. 参数表（新增/复用）

| 参数 | 值 | 位置 | 备注 |
|---|---|---|---|
| `KEEPER_PRED_MIN_SPEED_MPS` | 0.30 | param.py 新增 | 低于此速不预测 |
| `KEEPER_PRED_MAX_T_S` | 4.0 | 新增 | 光行时上限 |
| `KEEPER_PRED_MARGIN_M` | 0.25 | 新增 | 预测点内收门柱 |
| `KEEPER_TRACK_SPEED_MPS` | 1.60 | 新增 | 横移速度上限（omni） |
| `KEEPER_TRACK_DEADBAND_M` | 0.10 | 新增 | 防抖 |
| `KEEPER_LINE_INSET_M` | 0.20 | 复用 | 贴线 x=−6.8 |
| `KEEPER_CLEAR_RADIUS_M` | 1.35 | 复用 | Lead 要求的「1.35m 内解围」 |
| `KEEPER_CLEAR_POWER` | 6.0 | 复用 | |

## 7. 验证流程（T1 编码后）

1. `python -m py_compile src/*.py` + `python tools/replay_playcheck.py` 全 PASS。
2. 跑 v4.0b 2–3 场（建议仍并发下 3 单节约时间；但对局数按 2 场起算）。
3. 我做帧级验收：`analyze2.py` 取 crossing/keeper 序列 → A1/A2/A3；`instrfull.py` 统计 `normal:out_retreat` 帧/目标 → B1/B2；manifest penalty → C1/C2；`top_analyze2.py`/`s6_report.py` → D1/D2。
4. 通过后进入 P1（front_push 死代码 + 射程 6.5 m），再评估 v4.2 的 P2。
