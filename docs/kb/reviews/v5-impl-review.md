# v5 三机制「spec vs 实现」代码评审

**范围**：分支 `v5` 相对 main(`ef64d23`) 的 diff，三笔提交
- `717972a` v5-step1 Lever A：`src/player.py::_coordinated_kick_plan` 前场块重写（Z1 射线门控射 9.0 / Z2 避人推进 7.0 / Z3 贴线禁射长轴轻推 / Z2b 低平 pass / A-3.1 卡住 1.5 s 冷却）+ `_dist_point_to_segment`
- `6a04039` v5-step2 Lever C：`src/main.py::_update_touch_events` + `_act_normal` 内 P1/P2/P3 反抢指派 + `recover_until` 禁 slowball
- `dc9890d` v5-step3 Lever B：`src/main.py` box2 块重写 + `src/player.py::Player.one_touch_finish`

**方式**：只读代码 + 与 `docs/kb/reviews/v5-spec.md` 对照；未改 src/。门禁 30/30 PASS 只证明「无异常/无冻结」，不证明 M-05/纪律行为合理。

## 结论先行（给 T1 一行用）

**无 BLOCKING 项；有 3 条 SHOULD-FIX（约 40 行，建议 A/B 前修完再跑）**——否则可能污染 A/B 的 M-05 纪律红线与 C-2 机制兑现：
1. **box2 缺 2 s 超时回退**（M-05，中）— `store.box2_since` 只写不读，`BOX2_REST_R` 未消费；
2. **反抢窗口未限制球在场内**（R-06 间接风险，中低）— 球出界但裁判尚未 whistle 时 P1 会被派去追线外球，可能把已撤离的队友拉回摆球点；
3. **`RECOVER_FIRST_TOUCH_POWER` 未实现**（spec 偏差，低）— 夺回后的第一脚力度下限（≥5.5）没有落地，只实现了禁 slowball。

其余全部 PASS/NICE-TO-HAVE。若 credits 紧，至少修 1+2（约 20 行），3 可并入同批。

## ① 是否只在 NORMAL 生效 —— PASS

- Lever A 只从 `Player.attack()` → `_coordinated_kick_plan()` 生效（src/player.py:1190）；全仓库 `attack()` 仅两处调用：src/main.py:1000（slowball 分支）与 src/main.py:1010（forced_presser/正常 attacker），都在 `_act_normal`。
- Lever C press（src/main.py:775-858）、Lever B box2（src/main.py:1015-1095）都只在 `_act_normal` 内。
- `_act_normal` 只由 `play()` 在 `Phase.NORMAL` 分派（src/main.py:223-227）→ 开球/定位球/READY/STOPPED 不执行任何新行为。
- 唯一跨相位执行的是 `_update_touch_events()`（定义 src/main.py:549，play() 顶部 src/main.py:165 每帧调用）：**只写 store、不下发指令**；即使 STOPPED/SET_PLAY 期间被摆球位置跳变误触，press 是否启动仍由 `_act_normal` 的 `PLAYING && !stopped && set_play∈{None,NONE}` 二次门控（src/main.py:779-784）。
- **NICE-TO-HAVE**：在 `_update_touch_events` 里加「phase==NORMAL」过滤（一行），让 loss/recover 事件语义更干净；同时 `_clear_normal_sticky`（src/main.py:248）未清 press 相关 store——跨相位残留只在 1–2 s 内自然过期，当前无行为问题，但建议在 phase 切出 NORMAL 时清 `loss_t/press_until/recover_until` 更稳。

## ② 出界 / 后侧点安全 —— PASS（含 1 条 R-06 间接风险，见 SHOULD-FIX 2）

- 全部新踢球仍只经 `Player.kick()` → `_safe_kick_direction()`（src/player.py:303 调用；定义 :222，后侧点 `KICK_BEHIND_OFFSET_M=0.45`、`KICK_BEHIND_MARGIN_M=0.02` 夹进场内）；Lever A 的 front_shoot/front_push/front_pass/front_touchline_push、Lever C 的 press:clear、Lever B 的 box2:finish/box2:clear 都覆盖。
- 新目标点全部经 `_field_point(...,0.3~0.4)` 或显式 clamp（src/main.py:1059-1071、1087-1090；src/player.py 前场块），不会把「绕位点/后侧点」放到场外。
- Lever B 的 `one_touch_finish`（src/player.py:938-987）射门瞄 `goal_x−0.15`、被封堵时清向 `(half_l−1.0, ±1.2)` 仍在场内；`_safe_kick_direction` 兜底。
- **风险（中低，R-06 间接）**：press_window 没有「球在场内」条件（src/main.py:775-784）。球已出界、裁判 whistle 事件尚未到达时，P1 会被派 `press:first` 冲向 `_field_point(ball,0.4)`——即贴着边线/门线 0.4 m 处；随后 setPlay 出现，如果该点就是对方摆球点，等于把人的摆球点旁（v4.3 的 `out_restart_retreat` 在 press 之前执行：src/main.py:730-760，但 press 之后会把这些人重新派走）。建议：在 `press_window` 加 `abs(ball.x) <= half_l and abs(ball.y) <= half_w`（与 line_clear 的场内判据一致，src/player.py:1164-1167）。
- **NICE-TO-HAVE**：Lever A 的 Z1 被挡后走 Z2 push，当球在 x>5.8 时 `push_x=min(ball.x+2.2, half_l−1.2)` 实际把球往回收（朝中场）——可接受（避免底线），但建议注释说明「被挡后不硬射」。

## ③ M-05 inactive 回退 —— press PASS；box2 **风险中（SHOULD-FIX 1）**

- **Lever C**：P1/P2/P3 只在 `press_window`（`loss_t + PRESS_DURATION_S=2.0`，src/main.py:775-785）内被指派；下一帧窗口过期后它们回到 `field_players` 重新参与常规角色分配（support/box2/attack），不会站 >10 s。P1 满足 0.55 m 立即 clear。**PASS**。
- **Lever B box2**：预置后点分支（src/main.py:1053-1073）没有时间上限；`store.box2_since` 在 src/main.py:1075-1076 写入后从未被读取，`BOX2_REST_R=1.5`（src/param.py:545）也未被消费。可复现场景：球在 box 内 (e.g. (4.6,1.5)) 且速度 <1 或刚有快球，box2 在后点 (5.6,−0.9)，`box2_d=2.6 > BOX2_CRASH_R=2.0` → 走预置分支站着；球在 3 m 内 10 s → inactiveRobot。**风险中**。
  - 最小修法（~10 行）：预置分支里
    ```python
    since = getattr(store, "box2_since", None)
    if (since is not None and context.now - since > 2.0
            and box2_d > BOX2_REST_R and speed is not None and speed < 0.5):
        box2.action = "support:box2_reset"
        box2.move_to_position((BOX2_RESET_X, clamp(ball.y*0.5, -2.0, 2.0)))
        store.box2_id = None; store.box2_since = None
        rest = [q for q in rest if q is not box2]
    ```
    （或直接在预置分支给 box2 加 ±0.05 m 微摆，但 spec B-2 语义是「2 s 未触球回位」，建议前者。）
- **风险（低）**：press 在只剩 2 名 field_players 时 P3 不启用，不会出现「无人作为」；press 的 2 s 上限 + 后续正常分派保证不会 M-05。

## ④ 边界条件 —— PASS / 1 条死代码

| 检查项 | 结论 | 证据 |
|---|---|---|
| 球 None | PASS | `_act_normal` 顶部早退（src/main.py:624-626）；`attack()`、`one_touch_finish()`、`_update_touch_events()` 各自判空 |
| pose None | PASS | `active` 列表在 play() 内已过滤 pose（src/main.py:215-227），`_act_normal` 收到的都非 None；box2 `rest` 同源 |
| keeper 为空/门将选择 | PASS | keeper 在 `_act_normal` 内用 `min(players, dist(own_goal))` 恒有（players 非空）；`field_players` 排除 keeper（src/main.py:652），box2 不会选到门将 |
| 球速 None | PASS | 所有 speed 判断都写 `speed is None or ...`（src/main.py:1052、src/player.py 前场块 ball_speed is None）—— 仅「首帧被视为慢球」的保守偏置（低） |
| 对手封堵 | PASS | Z1 `_dist_point_to_segment` 1.2 m（src/player.py 前场块）；box2:finish 0.40 m（src/player.py:972-980）；封堵后都有退路 |
| 对手 park 场外 | PASS | 新逻辑全部基于球位置/距离，不依赖对手位姿；`opp_poses` 过滤 pose None |
| 反抢超时回退 | PASS | 2.0 s 窗口；`PRESS_ON_LOSS_WINDOW_S=2.5` 只写 store，不参与门控（注意这不是 bug，只是参数冗余） |
| **Z2b 不可达（死代码）** | **NICE-TO-HAVE** | 触发条件 ball.x>0 且 |y|≤4.5 ⇒ dist_goal ≤ hypot(7,4.5)=8.32 < `FRONT_Z2_MAX_DIST_M=12.0`，所以 `d>12` 的 Z2b 分支永远走不到（v5-spec §2 也写错）。建议删除该分支与 `FRONT_Z2_MAX_DIST_M`/`FRONT_Z2B_*` 参数，或把 Z2b 改为「Z2 push 通道被 2 人封堵」的备选。 |
| **RECOVER_FIRST_TOUCH_POWER 未使用** | **SHOULD-FIX 3（spec 偏差，低）** | `RECOVER_FIRST_TOUCH_POWER=5.5`（src/param.py:526）grep 仅定义处；当前只做了 `recover_until` 禁 slowball（src/main.py:861）。spec C-2 的「第一脚 ≥5.5」未兑现。建议在 `_coordinated_kick_plan` 返回前对 recover 窗口内 first-touch 取 `max(power, 5.5)`（或删参数，避免被误当成已验证）。 |

## ⑤ 与 v4.5b 纪律修复的冲突 —— PASS（未覆盖，仅 1 处顺序交互需注意）

v5 三笔提交没有删除/覆盖 v4.5b 的纪律逻辑；逐项核对：
- **slowball 滞回**（`SLOW_BALL_CLEAR_HOLD_S=0.8` 等，src/main.py:755-861）：仅新增 `and context.now >= recover_until` 作为进入条件（src/main.py:861），滞回与 hold 逻辑原样保留。
- **pre_retreat**（对方摆球期提前撤，src/main.py:1493-1519 `opp_setplay:pre_retreat`）：未被修改；press 只作用于 NORMAL，不影响 OPP_SET_PLAY 分支。
- **counter 站位**（`OPP_RESTART_WAIT_R_M=1.95`、`OPP_RESTART_TRIGGER_S=3.0`、`OPP_RESTART_COUNTER_SPEED=0.8`、`OPP_RESTART_SWING_RAD=0.0256`，src/main.py:1520-1556）：未改。
- **out_retreat / out_restart_retreat**（`BALL_OUT_RETREAT_M=2.4`、src/main.py:690-745）：未改；press 用 `out_retreater is None` 避开同时指派（src/main.py:783）。
- **交叉点（NICE-TO-HAVE）**：Lever A 前场块在原 v4.5 倒三角分支之后（src/player.py:360-390 的 `CROSS_X_MIN..CROSS_X_MAX & |y|>1.0` 优先于 Z1）。当球在 x∈[4.0,6.2]、|y|>1.0 且距门 ≤6.5 时会被 `attack:cross`/`attack:cross_near_post` 抢走，而不是 Z1 近距离射门——沿用 v4.5 设计，但 v5 里 Z1 本可射门，建议 A/B 后评估是否把「dist_goal≤4.0 且无门将封堵」提到 cross 之前。

## ⑥ 状态存储 / 回放可验证性 —— PASS（附清理建议）

- 新 store 字段都在 `init_store` 初始化（src/main.py:137-152），读取处均有默认值；无未初始化 AttributeError 风险。
- 回放可通过 action 标签直接验证（instrumented replay 统计）：
  - Lever A：`attack:front_shoot` / `attack:front_push` / `attack:front_pass` / `attack:front_touchline_push`
  - Lever C：`press:first` / `press:clear` / `press:block` / `press:lane`
  - Lever B：`support:box2_post` / `support:box2_rebound` / `support:box2_reset` / `box2:finish` / `box2:clear`
- **NICE-TO-HAVE**：`store.press_until` 只写不读（src/main.py:143/580）；`store.box2_since` 只写不读（见 SHOULD-FIX 1）；`_front_plan/_front_shot_until` 存 Player 实例、跨相位保留（行为无影响）。建议 A/B 后统一清理或补注释；若要量化反抢成功率，可加 `store.press_events` 计数（可选）。

## ⑦ A/B 准入结论

**可以进入 A/B，但建议先修 3 条 SHOULD-FIX（约 40 行，改动局部、风险低）：**

| # | 项 | 优先级 | 最小修法 |
|---|---|---|---|
| 1 | box2 预置分支无 2 s 回退（M-05） | **A/B 前修** | 用 `store.box2_since` + `BOX2_REST_R` 在预置分支加回位（src/main.py:1053-1077） |
| 2 | press 未限制球在场内（R-06 间接） | **A/B 前修（一行）** | `press_window` 加 `abs(ball.x)<=half_l and abs(ball.y)<=half_w`（src/main.py:775-784） |
| 3 | `RECOVER_FIRST_TOUCH_POWER` 未实现 | 可并入同批 | recover 窗口内 first-touch `max(power, 5.5)`（src/player.py 前场块返回处 / src/main.py attacker 路径） |

NICE-TO-HAVE（A/B 后清理）：Z2b 死代码、`press_until`/`box2_since` 冗余、`_update_touch_events` phase 过滤、cross 与 Z1 的优先级、`one_touch_finish` 开头 `release_kick()`、`fast_ball_until` 加「朝对方门速度>0」过滤。

**若 credits 紧张**：优先跑 Lever A+C 两场（修 2 后），Lever B 单独一轮（box2 的 M-05 需要 3–4 场样本观察）。A/B 场次按 spec：0707 / 张原硕 各一控一测（40 credits），逐场用 `/tmp/ra/s6_report.py` + instrumented action 直方图核对机制触发与纪律（R-06/R-07/M-02/inactive/fallen/stuck 全 0）。

---
评审人：replay-analyst（只读审查，未改 src/）。依据：`git show 717972a/6a04039/dc9890d`、`docs/kb/reviews/v5-spec.md`、v5 分支 `src/main.py`、`src/player.py`、`src/param.py`。
