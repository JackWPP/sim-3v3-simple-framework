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
