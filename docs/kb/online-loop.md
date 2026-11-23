# 线上迭代闭环（champion.booster.tech）

本地不再跑仿真，策略迭代走官方线上平台：拉对局 → 分析协同 → 改代码 → 离线构建 → 提交代码 → 线上对战 → 再分析。

## 1. 账号与登录态

- 平台：<https://champion.booster.tech>（3v3 第二季 / Arena）。
- 登录方式：浏览器登录后，页面 localStorage 里有 `booster_auth_token`（JWT）与 `booster_refresh_token`。
- 本机取得 token 的脚本（Chrome 需以调试端口启动）：

```bash
node /tmp/cdp.js eval 'localStorage.getItem("booster_auth_token")' | sed 's/^"//;s/"$//' > /tmp/.champ_token
```

- Token 有效期约 30 分钟；过期后刷新页面/重新登录，再执行上面一步即可。
- API 基座：`https://api.booster.tech/api/v1/competition`，请求头 `Authorization: Bearer <token>`。

## 2. 账号信息（当前）

- player：`e60b5555-ca10-4ffc-a099-6bf925822fd2`（Robot妙妙屋）
- team：`28c18f34-fbc1-4947-96ba-6bc82be8c624`，资格赛已过（AI 1:0）
- Arena 3v3：未定级（对战满 5 场定级），当前积分 1152；一场挑战 10 credits（余额 990）
- 提交的代码版本见 `GET /api/v1/competition/3v3/codes`

## 3. 代码提交（.agent）

1. `POST /3v3/codes/upload-url` body `{filename, size}` → `{file_key, upload_url, headers, expires_in}`
2. `PUT upload_url`（OSS 预签名，`Content-Type: application/octet-stream`）上传 .agent 文件
3. `POST /3v3/codes` body `{code_file_key, file_size, sha256, display_name, set_default: true}` 注册为默认参赛代码

`tools/online_submit.py` 封装了这三步（见仓库 tools/），离线构建产物来自
`docker run ... agent-dev ... /sdk/agent_bundler/build_pyagent .`。

## 4. 线上对战

- 页面「竞技场 → 发起挑战 → 自动匹配/排行榜高手/指定选手/赛事强队」都可发起。
- 每个挑战 10 credits；匹配后 `开始对战`，比赛在云端跑完（~600 模拟秒；约 10 分钟墙钟）。
- 也可直接调 API（推荐，免点 UI）：
  1. `GET /api/v1/competition/arenas/3v3/matchmaking/suggestion?mode=auto` → 建议对手（含 player_id）
  2. `POST /api/v1/competition/arenas/3v3/challenges` body
     `{opponent_player_id, idempotency_key(uuid≤128), expected_cost_display:"10.000000"}`
     → `{match_uuid, estimated_wait_seconds}`
  3. 轮询 `GET /api/v1/competition/matches/{match_uuid}` 直到 `state=finished`
- 浏览器内取 token 用 `/tmp/cdp.js api <METHOD> <PATH> [BODY]`（页面上下文 fetch，永远用最新 token，避免 30 分钟过期）。
- 代码提交注意：`upload-url` 的 `filename` 必须以 `.agent` 结尾（否则 40012），`display_name` 才是展示名。
- 对局记录 `GET /matches?player_id=<me>&ordering=-created_at`；单场 `GET /matches/{uuid}`。
- 回放：match 详情里 `realtime_replay.manifest_url` → manifest JSON（含 `events`、`segments`、`result` 统计）。
  `tools/online_match_fetch.py <uuid>` 会把详情/回放/manifest/segments 存到 `docs/kb/online-matches/`。

## 5. 复盘的协同指标

`tools/online_replay_analyze.py <replay.json>` 输出：

- 比分/犯规/进球/出界统计（来自 manifest `result`）
- 协同指标（10Hz frames）：
  - `avg_pair_dist_m`：我方两两平均间距
  - `pct_min_pair_lt_1m`：最近两台间距 <1m 的帧占比（挤球）
  - `pct_two_within_1_5m_ball`：2 台以上同时距球 <1.5m 的帧占比（抢球）
  - `avg_nearest_to_ball_m`：最近球员到球平均距离
  - `ball_in_home_half_pct`：球在主队半场的时间占比

## 6. 已知线上战绩

| 时间 | 类型 | 对手 | 比分 | 我方罚单 | 备注 |
|---|---|---|---|---|---|
| 11-18 | OFFICIAL 资格赛 | AI | 1:10 负 | 0 | 旧版本 |
| 11-19 | FREE_BATTLE | 哈基龙 | 0:3 负 | 1 罚 | 旧版本 |
| 11-21 | FREE_BATTLE | 楊 | 0:9 负 | 1 罚 | 旧版本 |
| 11-22 | OFFICIAL 资格赛 | AI | 1:0 胜 | 1 罚 | v1.14 通过资格赛 |
| 11-22 | FREE_BATTLE | 好好吃饭 | 1:2 负 | 2 罚 | v1.14；被最后一分钟绝杀 |
| 11-23 | FREE_BATTLE | 宋明晖（白银 #508） | **3:3 平** | 1 罚（inactiveRobot robot2） | v2.0 协同首战；评分 1171 |
| 11-23 | FREE_BATTLE | 阿白（白银，1242） | 0:4 负 | 2（illegalPosition/free_kick_avoidance） | v2.1；门将避球 bug 导致 4 球全失 |
| 11-23 | FREE_BATTLE | 地表最强（白银，1209） | **4:0 胜** | 0 | v2.2；4 球（211/346/536/636s），对手 9 罚；积分 1171→1196 |
| 11-23 | FREE_BATTLE | 瘤子牢孟（1135） | **4:1 胜** | 6（2×stopped_motion 0.31m + 4×fallenRobot） | v2.3；4 球（44/81/112/277s），对手 6 罚；support 前压导致挤球率回升到 19.6% |
| 11-23 | FREE_BATTLE | Adam Hariz_0997（1338） | 0:5 负 | 0 | v2.4；对手更强（1338），5 球全从门前被横穿，keeper 角色在深位机器人间切换 |
| 11-23 | FREE_BATTLE | w未来希望（青铜，1141） | 1:2 负 | 3（3×stopped_motion：0.301/0.303/0.330m，均为对方定位球摆球期快撤残留速度） | **v2.5**；我方 466.6s 进球、230.8s/713.0s 失球（终场前 8.5s 绝杀）；min_pair<1m 4.7%（历次最好）；ball_in_home_half 54.2%；11 次 set_play_retake 全在我方定位球（对方 10 罚）；评分 1209→1156 |
| 11-23 | FREE_BATTLE | 大魔王（白银，1206） | **1:1 平** | 0 | **v2.6**（ver11，sha 891ac82d…）；我方进球 sim533.8s、对方 sim463.3s；sim228.96s 我方 throwIn 第一脚直接进网被判 goal_disallowed_indirect（白丢 1 球）；retake 0（v2.5 是 11）；min_pair<1m 11.9%、球己方半场 48.9%；评分 1156→1161 |
| 11-23 | FREE_BATTLE | 群玉阁（1155，0胜1平3负） | **0:6 负** | 3（2×fallenRobot 三台同点互撞 + 1×stopped_motion 0.332m/2.9s，v2.7 慢爬跨过 1.5s 宽限） | **v2.7 回归**：③对齐门控+ENTER 1.0 使 kick 反复起停（105 次尝试/49% 成功、kick 活动帧减半），球在己方三区 70.5%、对方三区触球 0、0 进球；6 球全在 PLAYING 自家半场，5 球前一刻球静止 2–3s 而我方最近人 0.59–1.03m 不动；52.44s 门球第一脚横穿自家门口送角球；rating 1161→1124 |
| 11-23 | FREE_BATTLE | 高考加油（1217，0胜4负） | 进行中 | — | **v2.8**（ver13，sha 35b8458e…）：回退 v2.7③；保留门将 clamp/clear；①改宽限 1.15s@1.0 快撤后硬停；④横向轻推仅 ball.x>-2 |

## 7. v2.0 首战复盘（3:3 平，8f6e8d4e… 之外的新 match b8969e01）

数据来自 `final.json` + 68 个 segment（10Hz，5838 帧）：

- 进攻端明显改善：3 个进球（此前 v1.14 对人有 1-2 球），且**无 goal_disallowed / 无越界二次触球违规**。
- 防守端仍丢 3 球，三个失球有共同机制：**球横穿门线时门将 y 还停在旧值**（门将只按 `ball.y*0.65` 跟随）。
  - 失球 1（对方 291.9s）：门将 x=-6.43,y=0.54，球从 (-3.59,0.46) 滚到 (-7.16,0.69) → y 差 0.15m 但门将不在球线上。
  - 失球 2（383.5s）：我方 robot1 在 (-5.57,-1.28) 触碰后折射向自家门 (-7.45,0.35)，门将 y=-1.24 → 差 1.6m。
  - 失球 3（556.9s）：球 (-6.95,-0.79) → (-7.38,0.52)，门将 y=-0.88 → 差 1.4m。
- inactiveRobot：97.8s robot2 在对方角旗附近 (6.32,3.85) 站住（球 2.4m 内）→ 支援点被边线 clamp 到角旗。
- 协同指标（v2.0 vs v1.14 1:2 那场）：`avg_pair_dist` 4.69 vs 4.67m；`pct_min_pair_lt_1m` **12.2% vs 19.3%**（挤球明显减少）；`pct_two_within_1_5m_ball` 11.4% vs 12.7%；`avg_nearest_to_ball` 2.33 vs 2.11m；`ball_in_home_half` 47% vs 53%（把球推到对方半场）。
- 结论：协同结构改善，挤球下降，进攻能进球；下一个瓶颈是门将封角度与支援站位。

## 8. 协同问题 → v2.0 / v2.1 改动

- 问题（v1.14 三场人机复盘）：进攻无推进（一进踢球距离就朝门开大脚）、防守两台一起挤球、support 不参与进攻/保护、门将只站小禁区中央。
- v2.0：
  - `_act_normal`：先锁门将（离己方门最近者，不再当 attacker），其余两人一个 primary 一个 support。
  - `attack()`：距门 >6.5m 改为向前短推推进（避让最近对手）；≤6.5m 瞄门柱内侧射门；己方半场被逼抢改大力解围。
  - `support()`：进攻时前插到球前方 3.2m、横向偏移 2.5m 接应；防守时退到球—己方门连线 3.0m 并让开中路，不挤门将区。
- v2.1（针对 v2.0 首战暴露的问题）：
  - 门将：球在己方半场时按 `ball.y*0.9` 跟随、站位推到门线内侧 0.2m（封角度）；球在对方半场时保守跟随。
  - 支援：球进对方三区（x>2.5）改为「拖后接应」（球后 2.6m、横向 2.0m），不再前插到角旗；任何支援点强制距球 >=3.15m，并在球靠近时小幅摆动防 inactiveRobot。
  - 射门：瞄准点从门柱内侧 0.35m 收到 0.45m，力度上限 8.0→7.5，减少打飞/出底线。
  - `online_submit.py` 修复 filename 必须以 `.agent` 结尾。

## 9. 线上迭代记录（v2.0 → v2.2）

| 版本 | 对手 | 比分 | 我方罚单 | 对手罚单 | 关键指标（我方） |
|---|---|---|---|---|---|
| v2.0（首战） | 宋明晖（白银 #508） | 3:3 平 | 1（inactiveRobot） | 0 | avg_pair 4.69m；min_pair<1m 12.2%；2 台<1.5m 球 11.4%；avg_nearest 2.33m；球在己方半场 47% |
| v2.1 | 阿白（白银 1242） | 0:4 负 | 2（free_kick_avoidance 0.44m；另一次定位球） | 1 | avg_pair 5.39m；min_pair<1m 7.9%；2 台<1.5m 球 4.1%；avg_nearest 2.19m；球在己方半场 49.1% |
| v2.2 | 地表最强（白银 1209） | **4:0 胜** | **0** | **9**（7×free_kick_avoidance + 2×其他） | avg_pair 5.02m；min_pair<1m 13.4%；2 台<1.5m 球 6.3%；avg_nearest 3.04m；球在己方半场 **30.1%** |

- v2.1 复盘：协同指标继续改善（挤球 4.1%），但**门将避球 bug**（`walk_to(avoid_ball=True)` 让门将目标点≈球坐标时被斥力推开）导致 4 个失球全部是球横穿门线时门将 y 差 0.37~1.50m；同时我方在对方 throwIn 时距球 0.44m 吃 R-07。
- v2.2 修复：门将 `avoid_ball=False`；球进 `KEEPER_CLEAR_RADIUS_M=1.35` 且开放球权时踢走解围；球更深时贴门线站位（inset 0.1m）；对方定位球摆球期先快撤（1.2s 内 2.0m/s）再以 0.12m/s 爬出 1.45m 风险圈（低于裁判 0.15m/s 漂移阈值，不吃 M-02）。
- v2.2 效果：4:0、0 罚单、对手 9 罚（其 restart 干扰）；球在己方半场时间从 49% 降到 30%，反击/推进明显；
- 下一轮方向（v2.3）：①我方 avg_nearest_to_ball 3.04m 偏高 → primary 更积极上抢/压迫（但要保留 support 距离）；②进攻转化：4 球但射门次数/触球分布需看 frames；③set-play pass 偶发 retake（我方 throw-in 被 retake 3 次）需让第一脚更稳（目标点远离边线、力度更小）。

## 10. v2.3 / v2.4 复盘与改动

- v2.3（4:1 胜 瘤子牢孟）：
  - 改动：定位球第一脚落点内收（避边线 1.2m）、力度 4.0→3.6；support 前压阈值 2.5→0.8。
  - 结果：4 球、球在己方半场降到 24.2%；但 min_pair<1m 回升到 19.6%（前压导致挤球）、avg_nearest 3.48m；我方 6 罚：2×stopped_motion（0.307/0.313m 略超 0.3 阈值，**爬行阶段残余位移**）+ 4×fallenRobot（摔倒后 10s 未起身；官方 get_up 检测判 FAILED）。
  - 结论：support 前压过头；摆球期「爬行」不可取（0.3m/2s 预算太紧）。
- v2.4 改动（已提交 version 9）：
  - STOP_VACATE_WINDOW_S 1.2→0.6、STOP_VACATE_SPEED 2.0→1.5、**删除爬行阶段**（STOP_CRAWL_SPEED=0.0，宽限窗口内快撤，之后全停）；
  - SUPPORT_OFFENSE_X 0.8→1.5（前压回调，减少挤球）；
  - 保留 v2.3 的定位球安全落点。
- 仍待解决：fallenRobot（摔倒后起身失败，10s 罚）——属于框架/物理层，策略侧只能减少碰撞/倒地（后续可加「避免与对手贴身冲撞」的进攻路线选择）。

## 11. v2.4 → v2.5

- v2.4（0:5 负 Adam Hariz_0997，rating 1338）：
  - 0 罚单、2 次 goal_disallowed_indirect（我方定位球直接进球无效，符合二次触球规则）；
  - 5 个失球继续是门前被横穿：复盘中门将 y 与球门线穿越点差 0.18~1.0m，另有门将跑到 x=-7.35（球门线后方）→ 门将角色在两台深位机器人之间**反复切换**，两人互相推挤、门线出现空档；
  - 说明：v2.2 的 avoid_ball 修复有效，但深位队友挤占门将站位使 keeper 选择不稳定。
- v2.5 修复（version 10，提交未对战）：
  - `_act_normal`：门将角色**粘滞**（store.normal_keeper；上一帧门将仍在且离门不超过最优者 +1.5m 就保留），避免角色在两台深位机器人间抖动；
  - `guard()`：球在己方半场时按 ball.y **全量跟随**（gain 1.0、limit ±1.15），球更深时门将贴门线（inset 0.05m）。
- 下一轮验证：用 v2.5 打 2~3 场（尤其 rating 1300+ 对手），重点看失球数/门将稳定性；若稳定则可继续上调进攻投入（v2.6：双人前插 + 定位球二次触球后的补射）。
