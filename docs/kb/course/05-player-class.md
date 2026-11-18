# 05 了解 Player 类

> 来源：https://booster.feishu.cn/wiki/ZXdWwcXo2i555Dk8lIRcB2brnph（原文约 8700 字）

## 一、核心要点

- `Player` 是**单个机器人的遥控器**：把战术意图翻译成 SDK 能懂的指令。框架在 `SoccerRuntime` 初始化阶段按 `agent.toml` 配置的机器人数量自动造 3 个实例，`id` 固定为 1、2、3；**不要、也不应该自己实例化 Player**。
- 三个实例打包成 `players` 列表，作为 `play(context, players, store)` 的第二个参数传入，整场比赛存活。在 `_act_*` 里拿到哪个 `Player`，就是在给哪台机器人下指令。
- 所有动作最终收敛到**唯一出口** `set_velocity(vx, vy, vyaw)`（场地坐标系：vx 前进、vy 横移、vyaw 转向角速度，三者可同时下发）。要加日志、限速、安全检查，只改这一处。
- 发指令前先看"仪表盘"：`pose`（`Pose2D`，看不见为 `None`）、`mode`（非 `walk` 不能移动）、`is_fallen`（摔倒要先 `get_up()`）、`is_penalized`（罚下只能起身/切模式）、`is_kicking`（踢球中，用于可视化与迟滞）。
- **活性自理**统一走 `ensure_ready()`：摔倒 → `get_up()` 返回 `False`；`mode != "walk"` → `request_mode("walk")` 返回 `False`；否则 `True`。两个恢复动作都是**异步**的（几十到上百毫秒才生效），函数不能阻塞（全队 30 Hz，卡一帧全队停摆），语义是"我已经在处理了，但这一帧别指望他动"。
- `play()` 的正确姿势：每帧对**所有**球员调 `ensure_ready()`，把返回 `False`、`is_penalized`、`pose is None` 的排除出 `active`，只给 `active` 分派战术；受罚者也照常调 `ensure_ready()`，这样解罚后能立刻投入。
- 七个高层动作：`attack(kick_target=None)`、`guard()`、`support()`、`take_kickoff(kick_target=None)`、`walk_to(target, ...)`、`face_to(theta)`、`move_to_position(target)`。
- `attack()` 用**迟滞**决定"追球/踢球"：`KICK_ENTER_M = 2.0 m` 进、`KICK_EXIT_M = 2.5 m` 出，中间 0.5 m 是缓冲带。已在踢球态用宽松的 `EXIT`，未进入用严格的 `ENTER`；在 2.0~2.5 m 之间晃动时状态不变。
- `attack()` 追的**不是球本身**，而是 `_behind_ball()`：球→射门目标连线、从球沿背离目标方向退 `CHASE_BEHIND_M = 0.35 m` 的点。到位时面向球即对准球门——"用走位顺便完成瞄准"。
- `guard()` 站 `own_goal_area_center`（己方门线内侧 `goal_area_length/2` 处，y=0），`GUARD_FACE_BALL=True` 时一直面向球。它是**站桩型**动作，不会主动出击；要"对手逼近时上前封堵"得自己在 `_act_normal` 里判断威胁、改调 `walk_to`。
- `support()` 站"球 → 己方门中心"单位方向上距球 `SUPPORT_DIST_M = 3.0 m` 的点，用 `along = min(SUPPORT_DIST_M, d)` 防止越过球门，最后夹进场内（`x ≥ -length/2 + 0.3`，`|y| ≤ width/2 - 0.3`）。它是丢球后第一时间反抢的接应点。
- `kick(direction, power)` 的 `direction` 是**场地坐标下的弧度**，内部用当前 `pose.theta` 转成体坐标；`power` 自动夹到 `[KICK_POWER_MIN, KICK_POWER_MAX] = [1.0, 10.0]`，超范围真机会直接把自己踢摔。
- `release_kick()` 清除踢球迟滞标志 `_kicking`；`walk_to()` 开头会自动调它（"踢球状态下走位会被覆盖，先取消踢球状态"）。因此 `kick()` 之后每帧再 `walk_to()` 会不断打断踢球任务。
- 自定义行为的**三个正当理由**：① 现成动作表达不了战术意图（如堵传球路线）；② 把多个底层动作封装成一个稳定行为（走过去 + 到位转向 + 待命）；③ 在现成动作上加判断/修正（如 `support()` 但绝不越过中线）。
- **不该自定义**的三种情况：只调距离/力度/门槛 → 改 `param.py`；只换站位点 → 直接 `walk_to(新点)`；改"什么时候用哪个动作" → 那是状态机和角色分派的事（第 3 篇），不是动作本身的事。

## 二、代码与公式

**1）活性自理（原文 单元2，`src/player.py`）**

```python
def ensure_ready(self) -> bool:
    """摔倒→起身，非 walk→切模式（都异步、不产生移动）。
    返回本帧是否可执行动作（True=已就绪）。"""
    if self.is_fallen:
        self.get_up()
        return False
    if self.mode != "walk":
        self.request_mode("walk")
        return False
    return True
```

**2）`attack()` 迟滞（原文 单元3）**

```python
d = dist(self.pose.x, self.pose.y, ball.x, ball.y)
self._kicking = d <= (KICK_EXIT_M if self._kicking else KICK_ENTER_M)
if self._kicking:
    self.kick(kick_direction, kick_power)      # 进入踢球 → 踢
else:
    self.release_kick()
    self.walk_to(_behind_ball(ball.x, ball.y, kick_target, CHASE_BEHIND_M))
```

站位点公式（`_behind_ball`，`aim` 为射门目标，通常 `opponent_goal(ctx)`）：

```text
u  = (aim - ball) / |aim - ball|
p  = ball - u * CHASE_BEHIND_M        # 0.35 m，落在球背离球门的一侧
```

**3）`guard()`（原文 单元3）**

```python
home = own_goal_area_center(self.context) if self.context is not None else None
if home is None or self.pose is None:
    self.action = "guard:stop"; self.stop(); return

ball = self.context.ball if self.context is not None else None
face = 0.0
if GUARD_FACE_BALL and ball is not None:
    face = angle_to(self.pose.x, self.pose.y, ball.x, ball.y)

self.walk_to(home, face=face, avoid_ball=True, avoid_robots=True)
```

**4）`support()` 站位（原文 单元3）**

```python
gx, gy = own_goal(ctx); bx, by = ball.x, ball.y
dx, dy = gx - bx, gy - by
d = math.hypot(dx, dy)
ux, uy = (-1.0, 0.0) if d < 1e-6 else (dx / d, dy / d)
along = min(SUPPORT_DIST_M, d)                 # 3.0 m，且不越过球门
tx, ty = bx + ux * along, by + uy * along

half_l = ctx.field.length / 2.0
half_w = ctx.field.width / 2.0 - 0.3
tx = clamp(tx, -half_l + 0.3, half_l)          # 夹进场内
ty = clamp(ty, -half_w, half_w)
self.move_to_position((tx, ty))
```

**5）`kick()` 的坐标变换（原文 单元4）**

```python
dx = ball.x - pose.x; dy = ball.y - pose.y
ball_x_body = dx * cos_t + dy * sin_t          # 球相对我的位置，转到体坐标
ball_y_body = -dx * sin_t + dy * cos_t
direction_body = normalize_angle(kick_direction - pose.theta)
self._backend.kick(direction_body, power_clamped, ball_x_body, ball_y_body)
```

不做 `normalize_angle` 的话，359° 与 -1° 会被当成天差地别的两个方向，机器人会绕大圈转身。

**6）练习答案的几何（原文 单元6）**

```text
盯人：p = opponent_pose + unit(opponent_pose → own_goal) * 1.0
      # 从 context.opponents.get(opponent_id) 取位姿；face_to(angle_to(自己, 对手))
回防：target = (-4.0, clamp(ball.y, -3.0, 3.0))   # 己方大禁区前沿
```

## 三、易错点

- **【原文】** 不检查 `mode`/`is_fallen` 就发速度：底层**静默丢弃**，没有任何报错，表现为"机器人接到指令却一动不动"；若在起身动作中途收到速度指令，两套动作打架会出现抽搐、原地打转。
- **【原文】** `KICK_ENTER_M` 与 `KICK_EXIT_M` 写反（`ENTER ≥ EXIT`）就失去迟滞，机器人在边界反复抽搐。
- **【原文】** `walk_to` 内部 `release_kick()`，所以踢球中每帧调 `walk_to` 等于反复取消踢球任务；`kick` 后要留给动作物理时间（见 06 的冷却模式）。
- **【原文】** `guard()` 回位时 `avoid_ball=True` 必须开：守门员回位路上容易把球碰进自家球门，宁可绕远。
- **【原文】** `ARRIVE_DIST` 不要太小（默认 0.15 m），否则机器人会在目标点附近反复微调。
- **【原文】** `support()` 完全跟着球走，球快速横移时会跑得很辛苦；应改用 `store` 迟滞或区域防守。
- **【经验建议】** 本仓库 `src/player.py:631-633` 的 `support()` 在 `ctx` 非空后直接 `ball = self.context.ball` 再取 `.x`，`ball is None` 的帧会 `AttributeError`；`guard()` 已判空，`support()` 没判。应在函数开头补 `if ball is None: self.stop(); return`。
- **【经验建议】** `src/main.py:273` 的 `_act_our_kickoff` 直接 `attacker.kick(0.1, KICK_POWER_OUR_KICKOFF)`，没调用现成的 `take_kickoff()`；球员若还在球侧后方，`kick(0.1)` 的朝向是硬编码的，容易踢偏或踢空。
- **【经验建议】** `face_to()` 只发 `(0, 0, vyaw)`，会覆盖上一帧的平移速度；想"边走边转"应该用 `walk_to(..., face=...)` 而不是 `walk_to` + `face_to` 两连发。

## 四、对本项目的具体改进建议

1. **`src/player.py` → `guard()`：补威胁出击（把两个死参数用起来）。** 现在 `GUARD_THREAT_ENTER_X = -1.0`、`GUARD_THREAT_EXIT_X = -0.7` 在 `src/` 里无任何引用。改法：在 `guard()` 内当 `ball is not None` 且 `ball.x > GUARD_THREAT_ENTER_X` 时，目标点改为 `(clamp(ball.x, -field.length/2 + 0.4, GUARD_THREAT_ENTER_X), clamp(ball.y * 0.5, -1.2, 1.2))` 前压封堵；`ball.x < GUARD_THREAT_EXIT_X` 时回 `home`。用 `EXIT < ENTER` 形成迟滞（注意方向：这里是"进入威胁"用 ENTER，"解除"用 EXIT，需保证两阈值单调、不抖）。仍用 `walk_to(target, face=..., avoid_ball=True, avoid_robots=True)`，不碰球。
2. **`src/player.py` → `support()`：判空 + 参数化。** 开头补 `ball is None` 早退；把 `0.3` 的边距提成 `src/param.py` 的 `SUPPORT_EDGE_MARGIN_M = 0.3`，`clamp(tx, -half_l + SUPPORT_EDGE_MARGIN_M, half_l)`。
3. **`src/player.py` → `attack()`：增加 `aim` 参数。** 现在 `attack(kick_target)` 的 `kick_target` 只影响 `_behind_ball` 的绕后方向，真正踢的方向由 `plan_kick()` 固定朝对方门中心。建议签名改为 `attack(self, kick_target=None, aim=None)`，`aim` 传给 `plan_kick`，用于打近角/避开守门员（配合 08 的"射门选点"）。
4. **`src/player.py` → 新增两个技术动作（照抄练习）：**
   - `mark_opponent(self, opponent_id: int, dist_m: float = MARK_DIST_M)`：取 `context.opponents.get(id).pose`，`unit(对手 → 己方门) * dist_m` 得站位点，`walk_to(point)` 后 `face_to(angle_to(自己, 对手))`；对手不在我方半场则回 `support()`。
   - `fall_back_to_box(self, x: float = FALLBACK_X_M)`：目标 `(x, clamp(ball.y, -3.0, 3.0))`，直接 `move_to_position`；已在位（`dist < ARRIVE_DIST`）就不动，避免微调。
5. **`src/main.py` → `_act_our_kickoff`：改用 `take_kickoff()`。** 把 `attacker.kick(0.1, KICK_POWER_OUR_KICKOFF)` 换成 `attacker.take_kickoff()`，让主罚先按 `KICKOFF_STAGE_M` 绕到球后（`behind > KICKOFF_FRONT_MARGIN or lateral > KICKOFF_LATERAL_TOL` 时走 stage 点），就位后再 `attack()`；`store.kickoff_taker` 的锁定逻辑保留。
6. **`src/param.py` 新增：** `MARK_DIST_M = 1.0`、`FALLBACK_X_M = -4.0`、`SUPPORT_EDGE_MARGIN_M = 0.3`、`FACE_TOL_RAD = 0.1`（`walk_to` 到达后转向的 0.1 阈值），并在注释里写清单位与调大/调小的后果。
7. **`src/main.py` → `_act_ready`：** 用 `player.id` 映射站位槽位，替代 `players[0]/[1]/[2]` 的下标（附录 A 的坑，详见 08）。

## 五、原文关键摘录

| Player 的 property | 含义 | 用法 |
|---|---|---|
| `pose` | 当前位姿 `Pose2D`，看不见为 `None` | 走位/踢球的前提 |
| `mode` | 当前模式 | 非 walk 不能移动 |
| `is_fallen` | 是否摔倒 | 摔倒要先 `get_up()` |
| `is_penalized` | 是否被罚下 | 罚下只能起身/切模式 |
| `is_kicking` | 是否处于踢球中 | 用于可视化与迟滞 |

| 高层动作 | 行为 |
|---|---|
| `attack(target)` | 追球射门 |
| `guard()` | 守门，站小禁区中央待命 |
| `support()` | 站"球→己方门"连线上的补防点 |
| `take_kickoff()` | 我方开球：绕到球后、就位后踢 |
| `walk_to(target, ...)` | 走到目标点（带避障） |
| `face_to(theta)` | 原地转向到目标朝向 |
| `move_to_position(target)` | 走到站位点并面向球 |

| 底层接口 | 作用 | 注意 |
|---|---|---|
| `set_velocity(vx, vy, vyaw)` | 设定 x/y 线速度 + 转向角速度 | 真正让机器人动起来的唯一入口 |
| `stop()` | 速度清零 + 取消踢球 | 紧急停车用 |
| `kick(dir, power)` | 踢球（场地→体坐标自动转换） | `dir=None` 时自动调 `plan_kick()` |
| `release_kick()` | 清除踢球迟滞标志 | `walk_to` 开头会自动调用 |
| `ensure_ready()` | 摔倒→起身；非 walk→切模式 | 返回 `True` 才代表"本帧可动" |

> 原文："`attack()` 不是简单'看到球就踢'，而是用迟滞（hysteresis）判断何时进入/退出踢球状态，避免边界抖动。……进入踢球的门槛（2.0m）比退出门槛（2.5m）更小，这叫迟滞。"
>
> 原文："机器人不是走向球本身，而是走向球后方、球与球门连线的延长线上那个点 `_behind_ball(...)`。因为走到那儿时，机器人面向球就对准了球门方向，抬脚就能射。这就是用走位顺便完成瞄准的小心机。"
>
> 原文："`guard()` 是'站桩型'动作，它不会主动出击。如果你想要'对手逼近时守门员上前封堵'，需要自己在 `_act_normal` 里判断威胁、改调 `walk_to`。"
