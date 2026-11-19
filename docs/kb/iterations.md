# 迭代记录（iteration log）

> 每次跑完 `tools/matchrun.py --tag iteration-NN` 都会把整场数据存到
> `docs/kb/logs/iteration-NN.json`（+ `iteration-NN-runner/` 仿真器 runner 目录），
> 然后 `python3 tools/analyze_match.py docs/kb/logs/iteration-NN.json` 出摘要。
> 本表记录每轮比分/罚单/触球等指标与改动要点，是自迭代机制的经验载体。

## 队伍身份（重要，勿再搞错）

- 我方 agent = **team_id 1 = home 侧 = robot1/robot2/robot3**（Studio 虚拟机器人 h5t6r）。
  依据：仿真容器内 `/run/3v3_runner/team_1/sandbox.log` 里
  `supervisor start agent_id=com.example.lqinternalmatch team_id=1 robot_names=robot1,robot2,robot3`。
- 对手 = Booster AI = team2 = away = robot4/5/6。
- 裁判事件里 `home` 全部是我方；`sides=homeDefendsLeftGoal`，我方守 -x 门、攻 +x 门。

## 指标表

| 轮次 | 版本 | 比分(我方:对方) | 结果 | 我方罚单 | 对方罚单 | 我方触球 | 对方触球 | 事件数 | 时长(s) |
|---|---|---|---|---|---|---|---|---|---|
| baseline-01 | v1.0 示例代码 | 1 : 6 | 负 | 3（开球站位×2 + defender_touched_before_kick） | 0 | 25 | 25 | 149 | 668 |
| iteration-02 | v1.1 合规重写 | 2 : 2 | 平 | 4（R-07 free_kick_avoidance×3 + fallen×1） | 1 | 44 | 44 | 283 | 700 |
| iteration-03（中止） | v1.2 摆球宽限撤离+全向撤退 | 0 : 2（150s 中止） | 中止 | 1（M-02 stopped_motion 0.446m） | 0 | — | — | 67 | — |
| iteration-04 | v1.3 宽限期收紧+底线不追球 | 2 : 3 | 负 | **0** | 1（对方 R-07 干扰我们界外球） | 40 | 39 | 189 | 661 |
| iteration-05（无效） | v1.4 门将射线站位+出击 | 0 : 7（中止） | 无效（每 tick NameError） | — | — | — | — | 35 | — |
| iteration-06（无效） | v1.4b 回退门将改动 + support 纵深 | 0 : 6（中止） | 无效（context 全空，盲跑） | 2（inactiveRobot 被冻结误判） | 0 | 0 | — | 35 | — |
| iteration-07（无效） | v1.4b（部署时仍带崩溃点） | 0 : 2（中止） | 无效（847 次 tick failed） | — | — | — | — | — | — |
| iteration-08 | v1.4b（校验通过、干净重启） | 2 : 5 | 负 | 3（开球圈站位、SET 出对方半场、门球干扰） | 1（对方 fallen） | 18 | 17 | 149 | 683 |
| iteration-09 | v1.5 门将门线横移 + ready 槽位锁定 + hold_line 退到球后 2.2m + 支援纵深回退 | 3 : 2 | **胜** | 2（goalKick 干扰、goalKick R-07） | 2（R-07 ×2） | 38 | 38 | 299 | 715 |
| iteration-10 | v1.6 出界后不贴球（attack:ball_out 后退） | 5 : 3 | **胜** | 4（倒地被罚下×2、开球站位×2） | 0 | 30 | 30 | 193 | 701 |
| iteration-11 | v1.6 重跑（v1.7 尚未部署） | 3 : 2 | **胜** | **0** | 1（我们角球时对方 R-07 robot5） | 30 | 30 | 205 | 672 |
| iteration-12 | v1.7 我方开球非主罚球员退回本方半场/圈外 | 1 : 3 | 负 | 1（倒地被罚下） | 0 | 45 | 45 | 224 | 662 |
| iteration-13（无效） | v1.8 出界方向/射门力度/支援分离（引入 RobotState.id bug） | 0 : 4（中止） | 无效（每 tick AttributeError，全员冻结） | 1（inactiveRobot） | 0 | 13 | 12 | — | — |
| iteration-14（提速实验局） | v1.8b（修复 RobotState.id）@ 2.0–2.5x 仿真提速 | 0 : 3 | 负（不作 1x 有效对比） | 1（robot1 fallenRobot，get_up FAILED） | 1（goalKick 干扰） | — | — | 171 | 342（墙钟） |
| iteration-15 | v1.8b（定位球安全落点/射门力度随距离/支援分离/MAX_LINEAR 1.8）@ 1x | 4 : 2 | **胜** | **0** | 1（对方 robot4 fallenRobot） | 31 | 30 | 240 | 692（墙钟，sim 600，avg 0.87x） |

## 各轮改动要点

### baseline-01（示例代码，v1.0）
- 直接用官方 sample 逻辑：`_act_opp_set_play` 转 `_act_normal`（抢球）、`_act_our_kickoff`
  从开球点直接射（G-05 无效球）、`_act_opp_kickoff` 等待点距球 2.0m、`_act_our_set_play`
  四类型全转 normal。
- 结果：1:6 惨败；我方 3 张罚单都是开球/站位类（示例代码本身违规）。

### iteration-02（v1.1 合规重写）
- 重写全部 `_act_*`：
  - `_act_opp_set_play` 不再 attack/kick，门将回小禁区、其余人退到「球→己方门方向 3.3m」
    的等待点（>1.45m 判定线、>3m 避开 M-05）；
  - `_act_our_set_play` 按类型踢：角球传中、直接任意球/点球射门、界外球/球门球/间接任意球
    向前场踢；摆球 stopped 时全员静止；
  - `_act_ready` 改贪心槽位分配（不再按 players 下标）；
  - `_act_our_kickoff` 朝 +x 踢；`_act_opp_kickoff` 等待点 3.2m/本方半场/>3m；
  - `guard()` 加防 M-05 微移；`support()` 距离 3.5m。
- 结果：2:2；触球从 50→88，比赛活跃度明显提升；但吃了 3 张 R-07：
  对方球门球/界外球摆球后约 2.5s 就主罚，我方机器人要 180° 转身(约 1.6s)再走，
  来不及退出 1.45m → 罚 30s + 重踢。

### iteration-03（v1.2）
- 修 R-07 两条路：
  1. 摆球 stopped 阶段的 1.5s 刹车宽限期内，把仍在 2.7m 内的机器人**全向平移撤离**
     （新增 `Player.omni_move_toward`，不转身、体坐标 vx/vy）；
  2. `_act_opp_set_play` 里离球 <2.7m 的机器人同样用 omni 撤离，而不是先转身再走。
- `tools/matchrun.py` 增加赛后 `docker cp /run/3v3_runner` 归档我方 agent 日志。
- 新增 `STOP_GRACE_MOVE_S=1.2`、`OMNI_ESCAPE_SPEED=1.8` 参数。

### 部署校验协议（每次跑之前必做，血泪教训）

改完代码 → 部署前，**三步都过**：

1. `python3 -m py_compile src/player.py src/main.py src/param.py`（语法）；
2. `python3 tools/check_names.py`（全大写常量引用是否都在 param.py 定义；防
   `NameError: name 'KEEPER_STAND_OFF_M' is not defined` 这类只在运行时才炸的错）；
3. `booster.agent.run` 之后、**start 比赛之前**，`docker cp` 出 agent 日志确认：
   `grep -c "control loop tick failed"` 必须为 0，且最后一条 `tick #` 行里
   `game` 非 None、`teammates_seen=3/3`（否则就是 iteration-06 的盲跑）。

另外 `booster.agent.run` 之前**必须先 `booster.agent.stop`**，否则 Studio 会复用旧
simulator/game-control，新 agent 拿不到上下文。tools/matchrun.py 已内置 stop。

### iteration-05 / iteration-06（无效局，教训）
这两轮比分不作数，问题都在**部署/运行环境**，不是策略战术：

- **iteration-05（0:7 中止）**：agent 每帧抛 `NameError: name 'KEEPER_STAND_OFF_M' is not defined`
  （`player.py::guard()` 引用了 `param.py` 里实际不存在的常量）。runtime `_loop` 捕获异常后
  每 tick 全员停车 → 机器人冻结、0 触球、连丢 7 球。
  **教训**：改完 param.py 必须 `grep` 确认常量真的写进去了、且 `python3 -m py_compile` +
  本地 `python3 -c "import src.player"` 能过；部署前不检查，跑 11 分钟才发现是白跑。
- **iteration-06（0:6 中止）**：`end3v3Match` 后直接 `booster.agent.run`，Studio 复用了旧的
  simulator/game-control，新 agent 一个上下文都收不到（agent 日志 tick 行一直是
  `game=None ball=None teammates_seen=0/3 opponents_seen=0/3`），play() 永远 STOPPED →
  机器人冻结（还因此吃了 2 张 inactiveRobot）。**不是战术问题**。
  **修复**：`booster.agent.run` 之前先 `booster.agent.stop`（tools/matchrun.py 已内置）；
  每次 run 完先看 agent 日志最后一行的 tick 行，确认 `teammates_seen=3/3` 且 game 非 None，
  再 start3v3Match。
- 校验命令（比赛进行中也行）：
  ```bash
  docker cp h5t6r-k1:/run/3v3_runner /tmp/live_run
  L=$(ls -t /tmp/live_run/team_1/data/var/log/booster_agent/com.example.lqinternalmatch/agent_*.log | head -1)
  grep "tick #" "$L" | tail -3
  grep -c "control loop tick failed" "$L"   # 必须是 0
  ```

### iteration-03（v1.2，中止重跑）
- 开赛 16s 我方 robot1 吃 M-02 stopped_motion：`Robot moved 0.446m while GameControl
  stopped was active`，durationSinceStopped=2712ms，位置在 (7.07, 1.74) —— 即**对方
  底线/球门口附近**。
- 根因两条：
  1. GameControl 发布间隔 500ms，我方看到 stopped 可能晚 0.5s；1.2s 宽限期实际变成
     ~1.7s 才停，超过裁判 1.5s 宽限 → v1.3 把 `STOP_GRACE_MOVE_S` 收到 0.7s；
  2. `attack()` 追球追进对方球门区/底线外(x≈7.1)，对方球门球一摆球，我方就站在
     重启点旁边 → v1.3 在 `attack()` 里加「球贴对方底线(x > half_l-0.35)不追、退回
     half_l-1.4」和追球目标点 x 上限 half_l-0.5。
- 中止后直接用 v1.3 重跑 iteration-04。

### iteration-04（v1.3，首次 0 罚单）
- 2:3 负，但我们**全场 0 罚单**，合规修复（0.7s 宽限 + 全向撤离 + 底线不追）生效。
- 丢球：86.3s、455.8s、525.6s（对方进球）。末段 2:1 领先被逆转。
- 525.6s 丢球：对方 506.4s 触球后球在场上滚了 ~19s 才进，门将站固定小禁区中央
  没追 → v1.4 门将改为「球门中心→球 射线站位 + 明显更近时出击」。
- 584.1s 判 global_game_stuck：球停在对方底线 (6.88,1.77) 整整 30s 无人触球
  → 根因 v1.3 的 hold_line 在**活球**时也放弃追球。v1.4 改为只在对方重启
  （stopped / set_play 非 NONE）时才 hold_line。

## 评价指标（每轮关注）

1. **我方罚单数 = 0**（尤其 R-06 抢先触球、R-07 避让、M-02/M-05 静止/无活动、开球站位）；
2. 比分（先求不败，再求胜）；
3. 触球数/定位球次数（是否有效参与比赛）；
4. 我方定位球成功率、对方定位球防守成功率；
5. 比赛是否出现异常（球权长时间僵持、机器人卡住、无人进攻）。

## 工具链

```bash
# 桥（Studio DevTools 里的 renderer 轮询见 docs/kb/referee-mechanics.md 顶部说明）
curl -s http://127.0.0.1:8765/health

# 一键跑一场（build→run→start→watch→存档→摘要；约 13-15 分钟）
python3 -u tools/matchrun.py --tag iteration-04 | tee /tmp/matchrun-iter04.log

# 手工分步
python3 tools/bcmd.py --wait 240 booster.agent.build '{"workspacePath":"/home/xgx/wpp1/sim-3v3-simple-framework"}'
python3 tools/bcmd.py --wait 300 booster.agent.run   '{"workspacePath":"/home/xgx/wpp1/sim-3v3-simple-framework"}'
python3 tools/bcmd.py --wait 60 booster.agent.start3v3Match '{"workspacePath":"...","robotSerialNumber":"h5t6r","selectedScene":"football_match_pitch_6_K1"}'
python3 tools/matchw.py --out docs/kb/logs/iteration-04.json
python3 tools/analyze_match.py docs/kb/logs/iteration-04.json
```

## 规则依据

- 官方规则全文：`docs/kb/official-rules.md`
- 规则解读（App C 最严解读）：`docs/kb/rules-interpretation.md`
- 裁判实现细节（阈值/状态机/触球/罚则）：`docs/kb/referee-mechanics.md`
- 专题课摘要：`docs/kb/course/*.md`

### iteration-08（v1.4b，2:5 负）分析
- 我方 3 张罚单的根因链：
  1. `kickoff_non_kicking_side_in_center_circle`（59.4s）：对方开球，我方 robot1 离中心 1.55m。
     `_act_ready` 每帧按"离槽最近"重新贪心分配槽位，机器人移动过程中会互相交换槽位、来回走，
     导致 READY 始终凑不满"全员静止 5s"，45s 超时被强制进 SET，此时 robots 还在半路。
  2. `outside_own_half`（285.4s）：同上，READY 超时 → SET 时 robot3 还在对方半场（x=3.87m）。
  3. `defender_touched_before_kick`（313.8s）：对方 goalKick，我方 attacker 的 hold_line 只退到
     固定 x=half_l-1.4，与球门球摆球点(±6.0,±2.0)距离不足 1.45m，反而主动触球。
- 触球 18:17（iteration-04 是 40:39）：v1.4b 的 support 纵深约束让第三台机器人放弃中场，
  等于少打一人。→ 回退。
- 比分 2:5，但 13.1s 我方开球配合进球（说明 OUR_KICKOFF 的 kick+追球可行）。
- v1.5 修正：ready 槽位**进入 READY 时锁定**存 store.ready_assignment（禁止换人）；
  非开球方槽位离中心留 2.3m；hold_line 退到「球后方 2.2m」并夹到场内；
  support 回退；门将改为门线横移（球 y 投影，限制 ±1.05m）封射门角度。

### iteration-09（v1.5）改动清单
1. `src/main.py::_act_ready`：新增 `store.ready_assignment` 锁定；非开球方槽位
   `-circle_radius-0.8`（离中心 2.3m）；离开 READY 时清空锁定。
2. `src/player.py::guard`：门线横移 `home.y = clamp(ball.y*0.65, -1.05, 1.05)`（封角度）。
3. `src/player.py::attack`：hold_line 目标改为 `(ball.x-2.2, clamp(ball.y*0.3,±(half_w-0.3)))`。
4. `src/player.py::support`：回退 x<=-1.5 纵深约束（实验证明伤害进攻）。
5. 校验：py_compile + tools/check_names.py + 部署后 agent 日志 tick_failed=0、teammates_seen=3/3。

### iteration-09（v1.5，3:2 胜）分析
- 首次在有效局击败 Booster AI（此前有效局：1:6 负、2:2 平、2:3 负、2:5 负）。
- 触球 38:38，攻防参与均衡；门将门线横移后前 90s 未失球（此前版本常在 50-90s 丢球）。
- 我方剩余 2 张罚单都发生在【对方球门区/球出界处】：
  1. 97.1s defender_touched_before_kick：球出对方底线后 robot2 停在 (6.02,1.95)，
     裁判把球门球摆到 (6.0,1.93) 正好在机器人脚下 → 触球判干扰。
  2. 341.7s R-07：robot1 在对方球门区 (6.32,-1.87)，对方 goalKick 主罚触球瞬间距球 0.399m。
  根因相同：我方追球机器人会贴着"球出界点"停住，而摆球点就在出界点附近。
- 对方 2 张 R-07 也是同样机制（我们角球/界外球时对方 robot4/robot5 站太近），说明
  这一条对所有队伍都是高发罚单点。

### iteration-10（v1.6）改动清单
- `src/player.py::attack`：新增死球判断 `|ball.y| > width/2-0.15` 或 `|ball.x| > length/2-0.15`
  → `action="attack:ball_out"`，目标点 = `(clamp(ball.x*0.55), clamp(ball.y*0.55))`
  夹到场内 margin 1.5m，即离出界点/摆球点至少 ~2.4m，且不贴边。
- 目的：消除「摆球点在我方脚下」类 defender 干扰/R-07 罚单。

### iteration-10（v1.6，5:3 胜）分析
- 比分 5:3 创新高，但罚单回升到 4 张（对方 0 张）：
  1. 199.6s robot3 fallenRobot：被撞倒后 10s 内没起身（fallenDuration=10550ms，
     upDot=-0.03 仰面），裁判判 incapableRobot 罚下 30s。倒地起身是 BoosterOS 自带的
     自动恢复，策略层只能保证 `ensure_ready()` 每帧调用；多次连续被撞时仍可能超时。
  2. 333.9s robot1 fallenRobot：同样机制（fallenDuration=10018ms）。
  3. 541.4s / 542.5s robot2 + robot1 `kickoff_kicking_side_outside_center`：
     我方进球后 `_act_our_kickoff` 让非主罚球员 `p.stop()` 原地等待，但球权转换前
     两人还没回到本方半场（robotX=1.57 与 0.06，centerDistance 1.59/3.21），
     开球瞬间违反「开球方必须在本方半场或中圈内」。
- 触球 30:30、事件 193（出界后退生效后比赛更连贯，事件数比 i09 少但仍多于 baseline）。

### iteration-11（v1.7）改动清单
- `src/main.py::_act_our_kickoff`：非主罚球员不再原地 stop，而是检查位置：
  `p.pose.x > -0.3` 或 `dist(p.pose, 中圈心) < circle_radius+0.2`（即已越半场/踩圈）
  → `action="kickoff:reposition"` + `walk_to(_field_point(-1.0, ±2.4), face=0, avoid_robots=True)`；
  否则保持 `stop`。目标点 x=-1.0、|y|=2.4，离中心 2.6m > 1.55m、稳定在本方半场。
- 目标：消除开球瞬间「踢球方不在本方半场」的 30s 罚单（iteration-10 两张）。

### iteration-11（v1.6 重跑，3:2 胜，0 罚单）分析
- 注意：此局部署的 agent 仍是 v1.6（agent_20261118_152926.log），v1.7 开球站位修复此时**还未部署**
  （iteration-11 结束后才 deploy v1.7 并跑 iteration-12）。所以这是一次 v1.6 的重复验证。
- 结果：3:2 胜、我方 **0 罚单**、触球 30:30、events 205。进球 94.4/292.1/369.6s，失球 172.1/495.2s。
- 对方 1 张 R-07（232.6s 我方角球，robot5 distanceToBall=1.44m<1.45）→ 触发 set_play_retake，
  我们重踢；另有 551.9s global_game_stuck（30s 无人触球 → 坠球）。
- 结论：v1.6 的「球出界后后退」修复有效，同一份代码在 iteration-10 吃 4 张罚单、这里 0 张，
  说明罚单有随机性（对手干扰/倒地时机），评价至少要看 2-3 局。

### iteration-12（v1.7，1:3 负）分析
- v1.7 部署后首局：开球站位罚单清零（对比 iteration-10 的两张），说明修复有效。
- 但 1:3 输球，且 224 事件/45:45 触球说明比赛很碎：全场 13 次界外球/球门球/角球，
  球频繁出界（我方 throwIn 8 次、对方 5 次），定位球第一脚力度 8.0 可能太大，
  球容易直接飞出边线。进球效率对比：触球 45:45 但射门转化 1:3。
- 1 张罚单：455.9s robot1 fallenRobot（upDot=-0.03、height=0.07m、fallenDuration=10002ms，
  在对方 throwIn 的乱战中倒地，差 2ms 没起身）→ incapableRobot 30s。
  倒地 10s 罚下是 BoosterOS 自动起身能力的边界，策略层很难兜底，只能减少贴身缠斗。
- 末段 599.3s 又被进球（我方 595s 左右开球后丢球），开球后防反击仍需加强。
- 结论：v1.7 修复开球罚单成功；下一轮重点（v1.8）：
  1) 定位球力度下调（FORWARD 8.0→6.0 左右）并瞄准场内更安全的落点，减少界外球；
  2) 开球改为「回传/横传」而不是向前大脚，降低被反击风险；
  3) 减少三台机器人同时贴身抢球（被撞倒 + 乱战丢球）；
  4) 继续观察 fallenRobot 是否可接受为偶发。

### iteration-13（v1.8，无效局）分析
- 现象：0:4 惨败、TOUCHES home 13 : away 12、1 张 inactiveRobot（robot1，ballDistance=0.53m）、
  2 次 global_game_stuck（+36.7s、+264.3s，30000ms 无人触球 → droppedBall）；
  agent 日志 2931 次 `control loop tick failed`，异常 `AttributeError: 'RobotState' object has no attribute 'id'`。
- 根因：v1.8 新增的 support() 横向分离块遍历 `ctx.teammates.values()` 并访问 `mate.id`；
  但 `Context.teammates` 是 `dict[robot_id, RobotState]`，RobotState 没有 `.id` 字段
  → 每 tick 抛异常 → 全员冻结（所以出现 30s 无人触球与 0:4）。
- 修复：改为 `for mate_id, mate in ctx.teammates.items()`（key 就是机器人 id），并加注释；
  同时 grep 复核 src/main.py / src/player.py 其余 `.id` 用法都是 Player 对象（安全）。
- 教训：`tools/check_names.py` 只检查未定义的常量名，查不出属性误用；新增遍历/跨帧代码
  必须对照 `src/framework/types.py` 的字段（RobotState 有 pose / fall_down_state / mode / penalty 等，无 id）。

### iteration-14（v1.8b，2 倍速实验局，0:3）分析
- 目的：验证「Studio 容器 + set_speed」能否把迭代速度提上来。target_speed_factor 2.0 / 2.5 时
  比赛墙钟倍速实测 1.64x / 2.24x（受 Studio 3D 渲染争用限制，见下文性能实验）。
- 结果：0:3（home 0 : away 3）、duration 342s 墙钟、events 171；26.4s robot1 因 fallenRobot 吃
  incapableRobot 30s（upDot=0.55、height=0.09m、fallenDuration=10020ms）；127.6s global_game_stuck
  （30026ms 无人触球 → droppedBall），后续再丢 2 球。agent 日志 `player 1 get_up ended: status=FAILED
  error=Get-up command was sent but robot was not observed getting up within 5.000s`（官方 get_up 修复
  正确上报失败，而不是静默卡住）。
- 判断：2 倍速会放大控制/起身问题，**不能作为 1x 有效战绩**；但它证明了提速通道可用，
  适合冒烟测试/观战，或后续做「倍速下鲁棒性」专题。
- 归档修复：matchrun 的 watch 循环因桥 get3v3MatchStatus 单次耗时 35–46s 而失效；
  改为直接从容器取数：`/status`、`/events/history?limit=5000`（**默认 limit 只有 50**）、
  `/result`（全量 match 字段，但无 events），再 `docker cp /run/3v3_runner`，
  手工重建 `docs/kb/logs/iteration-14.json` 后用 `tools/analyze_match.py` 出摘要。

### iteration-15（v1.8b，1x 干净验证，4:2 胜）分析

- **结果**：home 4 : away 2，胜。duration 691.9s 墙钟（sim 600s，平均 0.87x，ratio 0.69–0.99 随 Studio 渲染争用波动），
  events 240，触球 31:30，**我方 0 罚单**（v1.8/v1.8b 首次在干净 1x 口径验证；此前 iteration-04/11 也是 0 罚单，
  但那时是 v1.3/v1.6，v1.8 的定位球安全落点改动首次验证）。
- **进球时间线**：away 142.5（0:1）→ home 197.4（1:1）→ home 288.6（2:1）→ home 423.0（3:1）→ away 505.3（3:2）
  → home 547.2（4:2）。首次在 v1.8 下多次落后/被追平后仍净胜 2 球，说明进攻端改善有效。
- **对方唯一罚单**：arena robot4 fallenRobot 358.6s（对方自己被罚下 30s），我方 0；
  与 iteration-14（2 倍速时我方 robot1 起身失败/摔倒被罚）对照，说明摔倒/起身失败是**提速导致**，1x 下稳定。
- **32.9s global_game_stuck**：开赛后约 30s 无人触球 → 坠球。说明开球后前 30s 进攻推进太慢（站位远/第一脚力度不足），
  是下一轮重点（开球后主动抢第一脚、提高前场触球概率）。
- **出界偏多**：throw_in_setup 10 次、corner_kick_setup 2 次、goal_kick_setup 3 次（总数比 i11 多），
  球频繁出界说明常规进攻射门角度/力度仍不够收敛；v1.8 的定位球方向已不再直接踢出界，但 plan_kick 的射门瞄准可继续调。
- **结论**：v1.8b 在 1x 有效局下成立（4:2 胜 + 0 罚单），作为当前最优版本；下一步：开球后前 30s 主动触球、
  射门角度收敛、减少不必要出界、迭代提速（1.5x 折中或 headless 纯物理）。

### 性能优化实验（2026-11-19，用户诉求 m02380：0.6x 太慢 → 省资源、快速迭代）
- 结论 1（运行期提速）：容器内 sim venv 连 `ws://127.0.0.1:8788`，发
  `{"type":"command","command":"set_speed","params":{"speed_factor":N}}` 即可。1.0x 基线约 486
  physics steps/s（dt≈2ms），2.0→821 steps/s（actual 2.0），3.0→1009（actual 2.59），4.0→1317
  （actual 4.0）；物理-only 上限约 1300 steps/s（≈2.7x）。Studio 同时做 3D 渲染时实际倍速
  约 1.6–2.2x（渲染争用 CPU）。
- 结论 2（headless 物理可行、完整比赛卡住）：/tmp/headless/{simsrc,library} + `virtual-robot:0.9.10-alpha-humble`
  + `--no-camera-relay --no-extension-process --no-clock-publisher --no-motion-* --no-control-server`
  可跑纯物理（500 步 step_us_p50=500µs）；但完整比赛链路（run.py 起 sandbox 激活 agent）失败：
  team_1 45s 未 Active，agent 日志 Booster OS 初始化出现 `Service not available`、
  `booster-cli robot_info timed out`、`Check failed: call_ == nullptr`（缺 Studio 会话下游服务，
  RpcService/agent manager 承载）→ 修复代价大，暂缓。
- 结论 3：提速不能用于策略有效性验证（2x 下摔倒/起身失败明显增加）；1x 仍是有效战绩唯一口径。
- 复现：
  `docker cp /tmp/set_speed.py h5t6r-k1:/tmp/`
  `docker exec h5t6r-k1 /usr/local/booster_robot/booster_robocup_sim/.venv/bin/python /tmp/set_speed.py 2.0`
  （恢复 1x 传 1.0；比赛进行中/结束后均可设，对新比赛也生效）。
- TODO（可选后续）：Studio 关掉 simulator 3D 窗口后的倍速上限；给 run.py 补 agent 激活所需服务；
  用 taskset 把渲染进程隔离到少数核。


## 性能/headless 实验（2026-11-19 晚）

**目标**：绕开 Studio 3D 渲染，把「改代码 → 跑一场」的迭代周期压短。

- Studio 模式实测：target=1.0 时实际 **0.69–0.99x**（3D 渲染/相机管线争用 CPU ~1.5-2 核），
  一场墙钟约 690–850s；`set_speed` 2.0 时实际 1.6–2.2x，但 2x 下摔倒/起身失败增加，
  不能作为策略有效性口径。
- headless 模式（`docs/kb/headless.md`，`tools/headless_match.py`）：不启渲染，1x 时
  实际 **0.97–0.99x**；`set_speed` 比赛中途生效后实测 ~1.2-1.5x（受 agent 进程与扩展 CPU 限制）。
- 结果：
  - headless-01：**2:1 胜**，墙钟 612s；后段出现冻结（~326s 后无触球、反复 global_game_stuck），
    记为无效/待复现。
  - headless-02：**2:1 胜**，墙钟 500s（开赛约 40s 后 set_speed(2.0)），全程触球到 575s，
    仅 1 次 game_stuck → headless 链路有效。
- 关键修复：headless 中 agent 激活耗时 ~95s（Booster OS 初始化超时回退），
  `run.py` 的 `wait_for_agents_ready` 超时需从 45s 调到 **180s**，否则误报
  `timed out waiting for agent lifecycle activation`。
- 产物：`docs/kb/logs/headless-01.json`、`headless-02.json`（+`*-runner/`）、`headless.md`。
- 待办：复现/修复 headless-01 后段冻结；研究降低 95s 激活开销；把 headless 结果纳入
  每轮迭代的快速烟测流程（Studio 作为最终口径）。

### headless-03（v1.9 首次验证，4:0 胜）分析

- 代码：v1.9 = 停摆期移动收紧（`STOP_GRACE_MOVE_S` 0.7→0.3、`OMNI_ESCAPE_SPEED` 1.8→1.2、
  只撤离距球 <1.6m 的机器人）、`attack()` 的 ball_out 判据改用官方出界线+余量
  （`|x|>half_l+0.15` / `|y|>half_w+0.15`，避免球仍在场内就放弃追球导致 30s 僵局）、
  定位球力度下调（FORWARD 5.5→5.0、CAP 8.5→8.0）、`_act_opp_set_play` 增加 stopped 兜底全静止。
- 首次使用**离线构建**（agent-dev 镜像 + `AGENT_SIGN_KEYSTORE=/.agent_dev/keystore.p12` 等），
  不再依赖 Studio GUI 构建；构建 12s。
- 结果：**4 : 0 胜**（home 4 : away 0），墙钟 481.8s（仿真 600s；headless 容器中模拟器
  target 仍沿用上一场的 2.0，实测约 1.25x），268 events，touch 26:25。
- 罚单：我方 2 / 对方 4。
  - 我方：robot3 `defender_touched_before_kick`（+233.6s，对方 throwIn，pos (6.65,-4.44)）、
    robot2 `stopped_motion`（+88.1s，对方 throwIn 摆球，moved 0.320m，durationSinceStopped 2498ms）。
  - 对方：2× `defender_touched_before_kick`（我方 throwIn/corner 被干扰）、
    2× `free_kick_avoidance_radius`（我方 cornerKick 时对方 robot4/robot6 分别 0.94m/0.54m）。
- 结论：进攻端明显改善（4 球，早期主动性 OK）；剩余我方罚单全是「球在角落/边线附近出界前
  贴得太近」的同一机制：v1.9 只在球**已出界**后才撤退，球滚向边线时仍贴上去抢，
  出界后裁判把摆球点放在原地附近 → 我们就在 1.45m 内。→ v1.10 修复见下。
- 归档：docs/kb/logs/headless-03.json、headless-03-runner/、headless-03-summary.txt。

## v1.9 / v1.10 改动清单（2026-11-19 晚）

### v1.9（headless-03 验证）
- `src/param.py`：`STOP_GRACE_MOVE_S` 0.7→0.3；`OMNI_ESCAPE_SPEED` 1.8→1.2；
  `KICK_POWER_SET_PLAY_FORWARD` 5.5→5.0；`KICK_POWER_CAP` 8.5→8.0。
- `src/player.py::attack`：ball_out 判据改为 `|y| > width/2+0.15` 或 `|x| > length/2+0.15`
  （官方出界线 + 0.15 余量），注释记录 iteration-15 的 32.9s game_stuck 教训。
- `src/main.py::_act_stopped`：vacate 仅对 `d_ball < RESTART_AVOID_RADIUS_M+0.15` 的机器人，
  目标改为 `_away_from_ball_point(..., 1.8m)`（短距离撤离）。
- `src/main.py::_act_opp_set_play`：顶部增加 `g.stopped` 兜底全员 `stop()`。

### v1.10（headless-04 验证，待填）
- `src/param.py`：`STOP_GRACE_MOVE_S` 0.3→0.0（完全取消摆球期移动，消灭 M-02 侧风险；
  靠 v1.10 的 line_hold 预先远离重启点来避免 R-06/R-07）。
- `src/player.py::attack`：新增「贴边线/底线 0.7m 带内保持 1.8m 距离」分支
  （`action="attack:line_hold"`，朝己方门方向退，clamp 场内 1.0m 余量）。
  根因：headless-03 我方 2 张罚单都是球滚向角落时贴太近，出界后摆球点就在脚下。
- 目的：同时压低 R-06/defender_touched_before_kick 与 M-02 stopped_motion。

### headless-04（v1.10）
- （待填）

### headless-04（v1.10 验证，1:1 平）
- 代码：v1.10 = 摆球期移动完全取消（`STOP_GRACE_MOVE_S` 0.3→0.0）+ `attack()` 新增
  「贴边线/底线 0.7m 带内保持 1.8m 距离」分支（`attack:line_hold`）。
- 构建：离线 build 832322B，sha256 `d9a771a7afc17f7fb80debe51be9006e9519cb2d9895d0172d004084370a100c`。
- 结果：**1 : 1 平**，duration 479.8s（≈1.25x），176 事件（归档时监控只抓到部分为 199/实际 176）。
- 罚单：我方 1（robot3 `inactiveRobot`，+249.1s，验收测量 inactiveDuration=72.0ms 异常地 < 阈值
  10000ms，疑裁判 headless 侧测量瑕疵；ballDistance=1.76m），对方 0。
- 关键问题（v1.11 修复）：
  1. **3 次 `goal_disallowed_indirect`**（+146.4 / +200.6 / +359.9s，均 actor=home，reason=
     `indirect_goal_requirement_not_satisfied`）→ 我方界外球/球门球/间接任意球第一脚直接长传
     进门不算（需二次触球）。v1.11 改为短传给最近队友，由队友完成第二次触球。
  2. **开局 34.3s `global_game_stuck`**（最后触球约 +4.3s）→ v1.10 的 line_hold 在球贴线时
     让所有机器人保持距离，球不再被触碰 → 30s 无触球坠球。v1.11 给 line_hold 加 6s 上限，
     超时改为「从场内一侧接近 + 向场中心解围」。
- 归档：docs/kb/logs/headless-04.json、headless-04-runner/、headless-04-summary.txt。

## v1.11 改动清单（2026-11-19 深夜，针对 headless-04 的两个问题）
- `src/param.py` 新增：`KICK_POWER_SET_PLAY_PASS=4.0`（需二次触球的定位球第一脚短传力度）、
  `LINE_HOLD_MAX_S=6.0`（line_hold 上限）、`KICK_POWER_LINE_CLEAR=4.5`（贴边线活球向场内解围力度）。
- `src/player.py`：
  - `Player.__init__` 增加 `_line_hold_since`。
  - `attack()` 贴边线分支：6s 内保持 1.8m 距离（防出界后在摆球点旁吃 R-06/R-07）；超时后
    `action="attack:line_clear"`，从场内一侧接近球并把球往场中心方向解围（避免 30s 僵局）。
  - 非贴边线/球出界时清空 `_line_hold_since`。
- `src/main.py::_set_play_kick_plan`：签名加 `taker_id`；界外球/球门球/间接任意球改为
  「短传给距球最近且非主罚的队友」（力度 `KICK_POWER_SET_PLAY_PASS`），无队友时退化为前推；
  角球/直接任意球/点球保持直接射门。
- `tools/headless_match.py`：`start_runner` 前置清理 `/tmp/booster_agent*`；`/match/start` 后
  等比赛真正 active/playing 再启动 monitor（避免读到上一场 finished 状态提前归档）。
- 构建：833064B，sha256 `5be54457a8965ecaa54f5d37761e1a942afc3e269bf32d3b354e9b04df825fb8`。

### headless-05（v1.11，0:2 负）分析
- 代码：v1.11 = 需二次触球的定位球改为短传给队友（`KICK_POWER_SET_PLAY_PASS=4.0`）
  + `line_hold` 加 6s 上限、超时转 `line_clear` 试图解围。
- 构建：833064B，sha256 `5be54457a8965ecaa54f5d37761e1a942afc3e269bf32d3b354e9b04df825fb8`。
- 结果：**0 : 2 负**，wall 451.4s，触球 25，0 罚单。
- 根因：`line_clear` 的接近点是 `_behind_ball`（球后方），该点被 clamp 回场内后机器人永远
  达不到「球后方」条件；球停在 (7.13, 1.9)（贴对方底线、仍在场内）无人触碰 → 连续 4 次
  30.05s 无触球触发 `global_game_stuck` → dropped ball → 循环。
- 归档：docs/kb/logs/headless-05.json、headless-05-runner/。

### v1.12 改动清单（去掉活球远离球的所有启发式）
- `src/player.py::attack`：删除 line_hold / line_clear 整段（含 `_line_hold_since`、`LINE_HOLD_MAX_S`）；
  改为只在 kick 判定处处理贴线球：`abs(ball.x) > half_l - 1.0 or abs(ball.y) > half_w - 1.0`
  → `action="attack:line_clear"`，朝场中心 `kick(angle_to(ball, center), KICK_POWER_LINE_CLEAR=4.5)`。
- 教训（h04/h05 各踩一次）：任何「活球时保持距离/绕到球后」的启发式，只要让机器人实际上
  不触球，就会 30s 无触球吃 `global_game_stuck`；球在场内就必须有人去触球，规则风险只在
  重启瞬间处理。
- 构建：832439B，sha256 `8604a99646363bf57968d7750d67669572bbcf0584f86a656cbecfdb125fd274`。

### headless-06（v1.12，2:4 负）分析
- 结果：**2 : 4 负**，wall 471.7s，0 罚单，0 次 game_stuck，触球 46（home 23）。
- 1 次 `goal_disallowed_kickoff`（+148.3s，actor=home）→ 我方开球仍直接射门（G-05 无效）。
- 归档：docs/kb/logs/headless-06.json、headless-06-runner/。

### v1.13 改动清单（开球第一脚不再射门）
- `src/main.py::_act_our_kickoff`：主罚不再 `kick(0.0, ...)` 直射；选距球最近队友，第一脚
  传给队友（`KICK_POWER_OUR_KICKOFF_PASS=4.2`），由队友完成第二次触球后再进攻；
  无队友时向己方半场侧向轻推（远离对方门，避免直射无效）。
- 构建 sha256 `e183e69c3cbdd36b08e6a273f8b60d7e50a7b3bdfd9fa867a3de77c5f71bcf92`。

### headless-07（v1.13，0:1 负）分析
- 结果：**0 : 1 负**，wall 481.5s，触球 55，2 次 game_stuck（+114.0/+598.3），0 次 disallowed。
- 我方 1 罚：`defender_touched_before_kick`（+14.4s，对方 throwIn → 快发时我方 robot1 仍在
  1.45m 内）。→ v1.14 加大出界后撤退距离。
- 归档：docs/kb/logs/headless-07.json、headless-07-runner/。

### v1.14 改动清单
- `src/player.py::attack` 球出界分支：撤退目标由 `0.35*ball` 计算并强制距球 ≥2.4m
  （原来只到 1.5-2m），降低对方快发界外球时被罚 R-06/R-07 的概率。
- headless-08 验证：**3:2 胜、0 我方罚单、0 stuck、0 disallowed、touch 73**（headless 循环中当前最佳：进攻与合规同时改善）。
- 构建：832945B，sha256 `7168f2462ab50d59b59bb64ea999533dcfa959ec707d29c00d878d015c01ad12`。

## headless 快循环验证记录（v1.9 → v1.14）

> 明细见 docs/kb/headless.md「5. 实验结果」；此处只记结论级一句话。

| tag | 版本 | 比分(我:对) | 结果 | wall(s) | stuck | disallowed | touch | 我方罚 |
|---|---|---|---|---|---|---|---|---|
| headless-03 | v1.9 | 4 : 0 | 胜 | 481.8 | 0 | 1 | 51 | 2 |
| headless-04 | v1.10 | 1 : 1 | 平 | 391.3 | 2 | 3 | 39 | 1 |
| headless-05 | v1.11 | 0 : 2 | 负 | 451.4 | 4 | 0 | 25 | 0 |
| headless-06 | v1.12 | 2 : 4 | 负 | 471.7 | 0 | 1 | 46 | 0 |
| headless-07 | v1.13 | 0 : 1 | 负 | 481.5 | 2 | 0 | 55 | 1 |
| headless-08 | v1.14 | 3 : 2 | **胜** | 481.5 | 0 | 0 | 73 | 0 |
