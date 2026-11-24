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
| 11-23 | FREE_BATTLE | 群玉阁（1155，0胜1平3负） | **0:6 负** | 3（2×fallenRobot 三台同点互撞 + 1×stopped_motion 0.332m/2.9s，v2.7 慢爬跨过 1.5s 宽限） | **v2.7 回归**（**主因更正**：_act_normal presser 分支 NameError → 球一停每帧抛异常、runtime 全员 stop 冻结；对齐门控是次要回归）：kick 105 次/49% 成功、kick 活动帧减半；球在己方三区 70.5%、对方三区触球 0、0 进球；6 球全在 PLAYING 自家半场，5 球前一刻球静止 2–3s 而我方最近人 0.59–1.03m 不动；52.44s 门球第一脚横穿自家门口送角球；rating 1161→1124 |
| 11-23 | FREE_BATTLE | 高考加油（1217，0胜4负） | **0:6 负** | 7（**全部 inactiveRobot**：robot1/2/2/3/3/1/3 @sim305.3/306.2/494.5/494.7/552.2/553.9/637.3） | **v2.8**（ver13，sha 35b8458e…）；**根因更正**：7 张 inactiveRobot 与 294–305s 三台无指令同源于 v2.7 引入的 NameError 全员冻结（非开球 stay 站桩）；球滚到 robot1 脚边 0.31m 静止 >10s；对方 2 罚（Illegal position/Fallen robot）；0 进球、失球 55.5/105.4/254.7/408.1/500.5/638.8；ball_in_home_half 86.2%、min_pair<1m 14.6%；retake 0；评分 1124→1098；→ v2.9 修开球期安全退让 |
| 11-23 | FREE_BATTLE | 蓝色禁区1（1104，1胜0平13负） | **2:0 胜** | 9（**全部 inactiveRobot**，robot1×7/robot2/robot3 @53.05/57.24/146.50/238.83/349.56/427.56/503.95/529.43/615.75） | **v2.9**（ver14，sha 7ce0e6a5…）：仍带 NameError（未修）→ 开球/活球期多次三台冻结；我方进球 sim154.08/250.43；retake 0；min_pair<1m 15.2%、avg_nearest 4.98；评分 1098→1133；**按 Lead 判为无效场次/不作迭代依据**（bug 所致） |
| 11-23 | FREE_BATTLE | 马里奥冲压（青铜，1215） | **1:2 负** | 0 | **v2.10**（ver15，sha da3d35ad…，带 OPP_KICKOFF `store` NameError 未修完）：我方 sim713.57s 进球（timeRemaining 10.2）、失球 sim37.47/592.52；**双方罚单 0:0**、retake 1、disallowed 0；协同 min_pair<1m 9.1%、two<1.5m 6.2%、avg_nearest 2.91、ball_in_home_half 54.1%（away pair 2.03/min 48.4% 明显更挤）；oob awarded 21/caused 11；73 段 sha 73/73、6353 帧；评分 1133→1109；**按 Lead 判为「半有效」仅作观测**（冻结窗口与进球严格相关）；→ v2.11 修 store 形参 + 双门禁 |
| 11-23 | FREE_BATTLE | Micky-Rex（未定级，1171） | **3:2 胜** | 0 | **v2.11**（ver16，sha d058171c…，干净版首战）：我方进球 sim110.87/216.57/462.16、失球 sim148.31/554.53（早前 204.7/426.3/529.0、118.4/491.5 为 timeRemaining）；对方 1 罚（fallenRobot robot5@75.0）；retake 0、disallowed 0；协同 min_pair<1m **8.5%**、two<1.5m_ball 3.9%、avg_pair 5.29、avg_nearest 2.81、ball_in_home_half **38.2%**（历次最好）；oob awarded 5/caused **14**（新信号：我方出界偏多）、对方 awarded 14/caused 5；open-play 三台同时无指令 ≥2s = **0 段**（冻结消失）；69 段 sha 69/69、5862 帧；评分 1109→1141（+32） |
| 11-23 | FREE_BATTLE | 123213（青铜，1087，0胜1平11负） | **1:2 负** | 2（stopped_motion 0.333m/2.69s@sim129.0；fallenRobot@sim710.9） | **v2.12**（ver17，sha b567b019…）：失球 sim96.8/183.5、我方进球 sim214.1；对方 496.5 进球被判 goal_disallowed_indirect；retake 0；协同 min_pair<1m 10.3%、two<1.5m 2.4%、avg_pair 4.42、avg_nearest 2.8、ball_in_home_half **60.6%**；oob awarded 14/caused 13；72 段 sha 72/72、6126 帧；评分 1141→1110 |
| 11-23 | FREE_BATTLE | 0707（未定级，1177，0胜0平2负） | **3:0 胜** | 2（defender_set_play_interference robot1@460.02；illegalPosition robot2@553.0 distanceToBall 1.005） | **v2.13**（ver18，sha 44cbfced…）：我方进球 sim152.07/365.6/661.31；**stopped_motion 0**（窗口 0.5 生效）；retake 2（对方重踢，我方定位球防守违例）；协同 min_pair<1m 9.0%、two<1.5m 3.5%、avg_pair 5.97、avg_nearest 2.62、ball_in_home_half **27.5%**（最佳）；oob awarded 17/caused 9；72 段 sha 72/72、6180 帧；评分 1110→1138（+28） |
| 11-23 | FREE_BATTLE | 你美式吧（青铜，1041，8 场） | **3:0 胜** | 1（stopped_motion robot2@sim118.99，0.3348m/2.372s，reference(6.888,−4.582) — 快撤 1.0m/s 残余跨 grace，非 crawl 主因） | **v2.14**（ver19，sha 8631fe18…）：我方进球 sim150.93/284.01/556.84；对方 21 罚（12×outside_own_half + 9×kickoff_kicking_side_outside_center，robot4/5/6 镜像站我方半场，约 245s 0 人在场）；对方 sim124.29 进球被判 goal_disallowed_own_free_kick；retake 0；协同 min_pair<1m 2.9%、two<1.5m 1.4%、avg_nearest 3.83、ball_in_home_half **14.8%**（受对方大量罚下失真）；oob awarded 3/caused 2；66 段 sha 66/66、5837 帧；评分 1138→1158（+20）；**数据有效性过滤：对方罚单 21>3 → 记无效，不作迭代依据（Lead/analyst）**；→ v2.15（M-02 latency 修订 + P1 门线球） |
| 11-23 | FREE_BATTLE | Micky-Rex（青铜，1078） | **4:5 负** | 0（双方 0 罚） | **v2.15**（ver21，sha f51b3690…）：4:2 领先到 367s 后连丢 3 球（sim 403/589/643.7 终场前 14s 绝杀）被逆转；retake 0、disallowed 0；avg_pair 4.34、min_pair<1m 10.0%、ball_in_home_half 48.8%、oob caused 7；5678 帧、66 段 sha 66/66；评分 1158→1128；clean 场但输弱队 → 下一轮重心转防守 |
| 11-23 | FREE_BATTLE | GEN.G_Sendi（青铜，1155） | **3:0 胜** | 1（fallenRobot robot2@sim604.9，对方半场倒地 10s，无关） | **v2.16**（ver22，sha a0e3f246…）：六项静态修法（orbit 3.1m+微摆、先径向拉出、门线补射去 pose 限制、角旗过滤、切向撤离、双段撤离）+失球后 3s 防守线+门将解围不追；**单场失球 0**、ball 半场 12.0%、rating 1128→1155；有效 7/10 | 待补 |
| 11-23 | FREE_BATTLE | 句号（青铜，1166） | **3:1 胜** | 3（fallenRobot×3：robot3@467.6/robot2@488.3/robot2@617.3） | **v2.16**（ver22）：我方 3 球（sim 106.5/240.4/645.5）、失球 490.4；retake 4；ball 半场 16.8%；rating 1155→1179；对方 7 罚（4 倒地+2 摆球干扰+1 出界，无 0 人期）→ **有效**（Lead 裁定，新过滤规则） | 待补 |
| 11-23 | FREE_BATTLE | 11_8342（白银，1237，4胜0平5负） | **1:1 平** | 0 | **v2.17**（ver23，sha 2bd91087…）：我方进球 sim212.58、失球 sim703.46、另一球被判 goal_disallowed_indirect（sim579.79）；双方 0 retake；home min_pair 15.1%、ball 半场 57.9%；oob 19 caused；rating 1179→1182（+3）、对方 1237→1229（-8）；对方 4 罚全 fallenRobot（无 0 人期）→ **有效（Lead 裁定）** |
| 11-23 | FREE_BATTLE | 高考加油（白银，1276，1胜0平4负） | **1:3 负** | 1（inactiveRobot robot3@sim485.2，ballDistance 0.47m） | **v2.17**（ver23，sha 2bd91087…）：我方进球 sim319.79、失球 sim51.6/419.17/574.14；retake 0；min_pair 6.9%、ball 半场 42.5%；rating 1182→1166（−16）、对方 1276→1326（+50）；有效局 10/10 达成 |
| 11-23 | FREE_BATTLE | WY（未定级，1182，0胜0平3负） | **2:5 负** | 0（对方 1 defender_set_play_interference） | **v2.20**（ver24，sha 9a4e6287…）：我方进球 sim56.5/582.9、失球 sim217.6/324.0/471.9/622.5/675.4；retake 1；min_pair 9.3%、ball 半场 61.8%；rating 1166→1147（−19）、对方 1182→1267；10/10 已达成后的加测场 |
| 11-23 | FREE_BATTLE | RayenFCB（未定级，1245，0胜0平2负） | **0:5 负** | 0（对方 0） | **v2.21**（ver25，sha 7d23aee3…）：失球 sim105.3/161.7/200.9/368.3/637.9、对方 1 球被吹 indirect；retake 2；min_pair 10.3%、avg_nearest 2.01m；rating 1147→1132（−15）、对方 1245→1316；加测场 |
| 11-23 | FREE_BATTLE | 刘曜华（未定级，1131，0胜1平2负） | **1:6 负** | 0（对方 0） | **v2.22**（ver26，sha da52fca0…）：我方进球 sim329.8、失球 sim79.9/168.6/362.2/463.1/513.9/579.0、对方 1 球被吹 indirect；min_pair 9.1%、ball 半场 75.1%、oob caused 2；rating 1132→1112（−20）；加测场/v2.22 测试场 |
| 11-23 | FREE_BATTLE | 火花骑士可莉（未定级，1163，0胜1平3负） | **0:5 负** | 0（对方 0） | **v2.17-rollback**（ver27，sha 7287ffb9…）：回退验证场；失球 sim77.7/261.6/302.6/406.9/581.1，对方 2 球被吹 indirect；min_pair 12.6%、ball 半场 69.7%、oob 12/12；rating 1112→1095（−17）；回退未逆转 → 停在 10/10 有效局里程碑 |
| 11-24 | FREE_BATTLE | 蓝色禁区1（青铜，1069，1胜0平14负） | **6:0 胜** | 1（fallenRobot@sim269.7，upDot −0.357） | **v2.23**（ver28，sha 3ecac51f…）：我方进球 sim72.4/131.9/259.2/341.6/458.2/599.2；0 失球；min_pair 17.7%、ball 半场 8.7%、oob caused 0；rating 1095→1114（+19）；**analyst 判无效**（对方三台整场冻结场外 y=−5、0 触球） |
| 11-24 | FREE_BATTLE | 啊对对队（未定级，1194，0胜0平2负） | **0:3 负** | 1（R-06 defender_set_play_interference robot1@sim232.3，+对方 retake） | **v2.24**（ver29，sha 880481d0…）：失球 sim54.4/153.3/535.4、对方 1 球被吹 own_free_kick；retake unconfirmed_set_play_ball_out@228.3；min_pair 12.3%、ball 半场 51.8%；rating 1114→1100（−14）；v2.24 首战未达预期 → 回滚 v2.23b |
| 11-24 | FREE_BATTLE | 大魔王（未定级，1260，1胜2平5负） | **0:5 负** | 1（fallenRobot robot3@509.0，对方 5 罚） | **v2.23b**（ver30，sha f731f048…）：失球 sim78.5/148.7/274.1/605.8/678.6；对方 5 次定位球犯规送 5 retake 未转化；min_pair 15.8%、ball 半场 72.8%；rating 1100→1088（−12）；v2.23b 基线场 1/3 |
| 11-24 | FREE_BATTLE | 11_8342（白银，1237，4胜0平5负） | **0:1 负** | 1（R-06 robot1@sim480.9，对方 5 罚/retake 7） | **v2.23b**（ver30）：失球 sim701.7、对方 1 球被吹 indirect；ball 半场 **89.9%**、oob caused 29；rating 1088→1076（−12）；v2.23b 基线场 2/3；R-06 复发→v2.25 修 #22 方向校验 |
| 11-24 | FREE_BATTLE | 马里奥冲压（1266） | **0:1 负** | 5（3×R-06 robot2 + fallenRobot + R-07） | **v2.23b**（ver30）：失球 sim759.7、对方 2 球被吹 indirect；retake 10；ball 半场 75.1%；rating 1076→1066（−10）；基线场 3/3；v2.25 修 #22 贴线外踢 + 贴线球退场 |
| 11-24 | FREE_BATTLE | 11_8342（1262） | **0:1 负** | 1（R-06 robot1@sim433.1） | **v2.25**（ver31）：失球 sim751.9、对方 1 球被吹 indirect；retake 7→**2**、R-06 3→1；ball 半场 74.3%、oob caused 26、0 进球；rating 1066→1056（−10）；小样本 1/3 |
| 11-24 | FREE_BATTLE | Diego y la gente（1069） | **3:0 胜** | 0 | **v2.25**（ver31）：我方 0 罚/对方 0、0 retake；rating 1056→1074（+18）；小样本 2/3（1 胜 1 负）；归档待补 |
| 11-24 | FREE_BATTLE | 句号（1106） | **1:4 负** | 0 | **v2.26**（ver32）：我方 0 罚/0 retake、对方 2 罚；失球 sim89.7/151.5/311.5/660.1、进球 sim556.9；ball 半场 69.7%、oob 11/11、min_pair 19.8%；rating 1074→1057（−17）；小样本 1/3 |
| 11-24 | FREE_BATTLE | 123213（1169） | **2:3 负** | 0 | **v2.26**（ver32）：进球 sim158.2/245.1、失球 sim280.1/411.9/501.2；0 罚/0 retake；ball 半场 62.4%、oob 8/15；rating 1057→1044（−13）；小样本 2/3 |
| 11-24 | FREE_BATTLE | 11_8342（1281） | **0:2 负** | 0 | **v2.26**（ver32）：失球 sim69.0/694.6、对方 1 球被吹 indirect；0 罚/retake 2；ball 半场 74.8%、oob 24/24；rating 1044→1036（−8）；v2.26 小样本 3/3 完成（全负但 0 罚/0 R-06/0 R-07） |
| 11-24 | FREE_BATTLE | 句号（1153） | **0:2 负** | 3（2 fallenRobot + R-06 robot1） | **v2.27**（ver33）：失球 sim231.8/666.0；0 进球；min_pair 25.1%/two 25.0%（挤球恶化）、ball 半场 64.6%；rating 1036→1023（−13）；小样本 1/3 |
| 11-24 | FREE_BATTLE | 123213（1213） | **1:3 负** | 0（对方 1） | **v2.27**（ver33）：进球 sim3.1、失球 sim54.8/238.6/556.0；ball 半场 82.6%、oob 5/15；rating 1023→1013（−10）；v2.27 两场 0:2/1:3 → **rejected**，转 v3.0 |

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
| 11-23 | FREE_BATTLE | 你美式吧（青铜，1041，8 场） | **3:0 胜** | 1（stopped_motion 0.335m/2.37s@sim119.0） | **v2.14**（ver19，sha 8631fe18…）：我方进球 sim150.93/284.01/556.84；对方 21 张 illegalPosition（12 outside_own_half + 9 kickoff_kicking_side_outside_center，成批 30s）；对方 1 球被判 goal_disallowed_own_free_kick；retake 0；协同 min_pair<1m 2.9%、two<1.5m 1.4%、avg_pair 5.26、avg_nearest 3.83、ball_in_home_half **14.8%**；oob awarded 3/caused 2；66 段 sha 66/66、5837 帧；评分 1138→1158（+20），对方 1041→999 |

## 12. 线上有效局 10/10 里程碑（2026-11-23 22:13）

- 有效 10 场 = #1(v2.5)、#2(v2.6)、#7(v2.11)、#8(v2.12)、#9(v2.13)、#11(v2.15)、#12(v2.16)、#13(v2.16)、#14(v2.17)、#15(v2.17)；**4 胜 2 平 4 负**。
- 全部 15 场（150 credits）：无效 3 场（NameError 全员冻结 #3/#4/#5）、半有效 1（#6）、数据失真无效 1（#10 对方 21 罚）。
- 最大收获：①`src/main.py` presser 裸 `ball` 与 `_act_opp_kickoff` 缺 `store` 两处 NameError → 全队冻结，靠离线回放自检 `tools/replay_playcheck.py` + 静态门禁 `tools/static_check.py` 定位并固化为提交前必跑门禁；②时间口径：`timing.primaryTime` 是 timeRemaining，sim 时间用 `event.simTime`；③数据有效性过滤：对方 0 人期>60s 或对方罚单≥10 才判无效，避免把「对方自身失误多」误判成数据失真。
- 有效期内罚单趋势：3→0→0→2→2→0→1→3→0→1；stopped_motion 自 v2.13 后未再出现；R-06/R-07/M-02 全零已连续多场（#11 起）。
- 最终线上默认代码：v2.20（ver24，sha256 9a4e6287…，851576B），含 v2.18 三项 + analyst 第 14 场两条（门将预测跨半场、定位球第一脚限距 5m/力度 3.4）。
- 下一阶段：继续用 v2.20 跑对局，重点防守（对方长射、门将预测）与定位球合规；单场失球≤2 为验收线。

## 13. 新阶段（一整天连续迭代，目标 30–50 场）

### 13.1 v2.27 rejected / v3.0 A/B（2026-11-24）

| # | 时间 | 版本 | 对手(评级) | 比分 | 我方罚单 | min_pair<1m / 球己方半场 | 备注 |
|---|---|---|---|---|---|---|---|
| 30 | 04:06 | v2.27 ver33 | 句号(1153) | 0:2 负 | 3 | 25.1% / 64.6% | 挤球最差、R-06 复发 → v2.27 rejected |
| 31 | 04:21 | v2.27 ver33 | 123213(1213) | 1:3 负 | 0 | 10.0% / 82.6% | v2.27 第 2 场，按 Lead 停第 3 场 |
| 32 | 04:44 | **v3.0 ver34** | 句号(1185) | 1:1 平 | 0 | 13.8% / 58.5% | A/B 1/3 全项达标；rating 1013→1021(+8) |

v3.0 = restore v2.16(535766a) + 2 patches（#22 越界分量夹取 + 门口容差带），门禁 35/35 PASS，commit 4c54bd5；验收线 ball 半场<60%、失球≤2、进球≥1、罚单≤1、0 R-06。
| 33 | 05:00 | v3.0 ver34 | 123213(1242) | 0:1 负 | 1 | 11.8% / 66.7% | A/B 2/3 不达标（0 进球+R-06+球半场 66.7%）；rating 1021→1012(−9) |
| 34 | 05:15 | v3.0 ver34 | lhz(1061) | **3:0 胜** | 0 | 归档缺失 / 归档缺失 | 0 罚/0 失球/3 进球；rating 1012→1032(+20)；回放不可用 |
| 35 | 05:17 | v3.0 ver34 | qwsd(1099) | 1:1 平 | 1(R-06) | 16.1% / 46.9% | 对方 8 罚+2 球被吹；rating 1032→1035(+3)；触发 v3.1 重启自伤修复 |
| 36 | 05:46 | v3.1 ver35 | 123213(1242) | 0:2 负 | 5（4 stopped_motion+1 fallen） | 7.6% / 63.2% | R-06/R-07=0 ✓ 但 vacate 1.2m/s 残余跨阈 → v3.1b 速度 0.8 |
| 37 | 06:12 | v3.1b ver36 | 句号(1166) | 0:3 负 | 1（stopped_motion 边际） | 14.7% / 52.9% | R-06/R-07=0 ✓、ball 52.9% ✓，但 0 进球/失 3；rating 1027→1015(−12) |
| 38 | 06:27 | v3.1b ver36 | omo(1096) | 0:1 负 | 5（4 stopped_motion+R-06） | 13.2% / 58.4% | R-06 复发+4×M-02 边际 → v3.1b 罚单回归；rating 1015→1001(−14) |
| 39 | 06:42 | v3.1b ver36 | Messi(1091) | **1:0 胜** | 3（M-02 边际） | 8.5% / 5.1% | 唯一胜场；v3.1b 结论=罚单回归不保留；rating 1001→1022(+21) |
| 40 | 07:06 | v3.2 ver37 | 初号机(1086) | **2:2 平** | 0 | 10.6% / 39.3% | v3.2 首场验收全项达标（0 M-02/0 R-06/0 R-07、ball 39.3%）；rating 1022→1024(+2) |
| 41 | 07:22 | v3.2 ver37 | 3ala allah(1002) | 1:3 负 | 1（fallenRobot） | 12.8% / 29.2% | 纪律全过但终场前66s连丢2球（1:1→1:3），输弱旅；rating 1024→1007(−17) |
| 42 | 07:37 | v3.2 ver37 | 如果以后(1086) | **1:1 平** | 1（inactiveRobot） | 11.2% / 31.5% | v3.2 小样本 2/3 达标（纪律 0/0/0、ball 31.5%）；rating 1007→1011(+4) |

### v3.2 小样本小结（#40–#42）
- 战绩：2 平 1 负（2:2 / 1:3 / 1:1）；进球 4 失球 6；rating 1022→1011（净 −11）。
- 纪律：3 场 **0 M-02 / 0 R-06 / 0 R-07**（罚单仅 1 fallenRobot + 1 inactiveRobot）。
- ball 半场：39.3% / 29.2% / 31.5%（v3.0 47–67%）→ 明显改善。
- 结论：v3.2 达验收（2/3 场满足），保留为长期基线候选；待修=己方三区慢球（5 失球中 4 个同链）→ v3.3 单点改动。
| 43 | 08:05 | v3.3 ver38 | 北京市第二中学分校张原硕同学3(1059) | **0:0 平** | 1（R-06 robot1@429.99） | 12.3% / 37.1% | v3.3 首场：0 M-02、ball 37.1%、失球 0，但 R-06 1 次 + 0 进球；rating 1011→1013(+2) |
| 44 | 08:20 | v3.3 ver38 | Leinstein(1040) | 1:5 负 | 0 | 11.0% / 61.8% | v3.3 样本 2/3：0 罚但失 5、ball 61.8% → v3.3 rejected；rating 1013→998(−15) |
| 43-44 | 08:05-08:20 | v3.3 ver38 | 张原硕(1059)/Leinstein(1040) | 0:0 平 / 1:5 负 | 1/0 | 37.1% / 61.8% | v3.3 rejected（R-06 未除、失球未改善）；rating 1011→998；转 v3.3b 几何修复（chord/1.6m 圈/line_clear） |
| 45 | 09:08 | v3.3b ver39 | 蓝色禁区(1007) | **3:0 胜** | 1（inactiveRobot robot1@339.21） | 13.5% / 6.6% | v3.3b 样本 1/2：验收全项达标（0 M-02/R-06/R-07、ball 6.6%、失球 0）；rating 998→1015(+17) |
| 46 | 09:21 | v3.3b ver39 | Audi(1004) | 1:1 平 | 1（R-06 robot1@415.00） | 17.9% / 58.0% | v3.3b 样本 2/2：R-06=1 不达标（其余达标）；rating 1015→1015；#45 判无效（对手弃赛）→ v3.3b 无有效验收场，转 v3.3c |
| 47 | 09:52 | v3.3c ver40 | 如果以后(1076) | **2:0 胜** | 1（illegalPosition/R-07 robot1@430.65） | 6.5% / 21.3% | v3.3c 样本 1/2：inactiveRobot=0、R-06=0、ball 21.3%、失球 0、进球 2；唯一 R-07 1 张；rating 1015→1035(+20) |
| 48 | 10:08 | v3.3c ver40 | Messi(1014) | **0:0 平** | 0（对方 9 罚） | 17.5% / 39.7% | v3.3c 样本 2/2：0 罚、0 R-06/R-07/M-02、失球 0；进球 0；rating 1035→1034(−1)；v3.3c 作底 |
| 49 | 10:38 | v3.3d ver41 | moli_01(1104) | **1:1 平** | 0（对方 1 inactiveRobot） | 10.7% / 54.4% | v3.3d 1/3：0 罚、0 R-06/R-07/M-02、失球 1、进球 1；并发测试场（#50 同时 live）；rating 1034→1037(+3) |
| 50 | 10:39 | v3.3d ver41 | qwsd(1091) | **1:1 平** | 1（inactiveRobot@475.94） | 8.8% / 50.6% | v3.3d 2/3（并发）：M-02/R-06/R-07=0、失球 1、进球 1；唯一 inactiveRobot 1 张；rating 1037→1039(+2) |
| 51 | 10:53 | v3.3d ver41 | 112321312312(993) | **4:1 胜** | 0（对方 4 罚） | 12.7% / 46.2% | v3.3d 3/3：0 罚、0 M-02/R-06/R-07、失球 1、进球 4；rating 1039→1053(+14)；v3.3d 验收通过（1胜2平/进球6失球3/罚单1） |
| 52 | 11:24 | v4.0a ver42 | 句号(1191) | **0:1 负** | 0（对方 5 罚） | 15.2% / 33.2% | v4.0a 1/3：travel_med 0.56、long 1.4%、shots 4、box touch 2；rating 1069→1058(−11) |
| 53 | 11:24 | v4.0a ver42 | 初号机(1070) | **3:2 胜** | 2（对方 1 罚） | 9.1% / 46.3% | v4.0a 2/3：travel_med 1.37、dead 40.7%、shots 4、box touch 3；rating 1053→1069(+16) |
| 54 | 11:24 | v4.0a ver42 | omo(1118) | **0:0 平** | 0（对方 0 罚） | 19.9% / 85.7% | v4.0a 3/3：travel_med 1.23、dead 46.1%、box touch 0、ball 85.7% 被压制；对方 7 球被判 indirect；rating 1058→1061(+3) |
| 55 | 11:47 | v4.0a ver42 | 11_8342(1237) | **0:0 平** | 0（对方 4 罚） | 17.0% / 78.5% | v4.0a 4/5：ball 78.5%、0 进球、0 罚；rating 1062→1071(+9) |
| 56 | 11:47 | v4.0a ver42 | moli_01(1104) | **1:1 平** | 0（对方 1 罚） | 10.9% / 40.8% | v4.0a 5/5：ball 40.8%、0 罚；rating 1061→1062(+1) |
| 57 | 12:23 | v4.1 ver43 | 句号(1216) | **2:0 胜** | 0（对方 4 罚） | 14.5% / 53.5% | v4.1 1/3：travel 1.14、dead 44.8%、box 392/0；rating 1088→1110(+22) |
| 58 | 12:23 | v4.1 ver43 | omo(1113) | **1:1 平** | 2（对方 1 罚；1 R-06+1 R-07） | 14.8% / 82.9% | v4.1 2/3：travel 1.61、dead 41.6%、ball 82.9%；rating 1110→1110(0) |
| 59 | 12:23 | v4.1 ver43 | moli_01(1090) | **2:1 胜** | 1（对方 0 罚） | 13.8% / 50.6% | v4.1 3/3：box touch 5、travel 0.63；rating 1071→1088(+17)；v4.1 小结 2胜1平/进球5失球2/罚单3/rating+39 |
| 60 | 13:54 | v4.2 ver44 | VicMaster(1208) | 1:1 平 | 1（R-06 末段） | 77.5% / 12.3% | 强敌压力测试；ball 77.5%、9 对方间接球被吹 |
| 61 | 13:52 | v4.2 ver44 | wenqing(1186) | 1:3 负 | 1（fallen） | 78.3% / 21.7% | ball 78.3% 被压制 |
| 62 | 13:50 | v4.2 ver44 | Kungfu Lee(1170) | 2:0 胜 | 1（inactiveRobot） | 27.8% / 10.0% | 2:0 胜、0 失球；唯一 inactiveRobot 死锁 |
| 63 | 13:54 | v4.2 ver44 | iluip(1188) | 3:3 平 | 1（fallen） | 64.7% / 18.3% | 0 R-06/R-07、3:3；v4.2 4 场 1胜2平1负 rating 1110→1119 |
| 64 | 14:10 | v4.2 ver44 | 蓝色禁区1(1038) | 5:0 胜 | 1（踢球前触球） | 0.0% / 12.9% | 5:0、0 失球；rating 1130→1143 |
| 65 | 14:15 | v4.2 ver44 | 你美式吧(932) | 4:0 胜 | 0 | 18.9% / 12.5% | 对方 15 罚+12 无效球 → 判无效 |
| 66 | 14:01 | v4.2 ver44 | lhz(993) | 3:0 胜 | 0 | — / — | 归档缺失 → 判无效 |
| 67 | 14:13 | v4.2 ver44 | 张原硕(1051) | 0:0 平 | 1（踢球前触球） | 43.7% / 4.3% | 0:0、oob caused 4；rating 1143→1139 |
| 68 | 14:52 | v4.3 ver45 | 蓝色禁区1(1014) | 7:0 胜 | 0 | 0.0% / 13.6% | v4.3 首战 7:0、0 失球；rating 1147→1158 |
| 71 | 14:55 | v4.3 ver45 | yzy_7877(1181) | 0:0 平 | 1（未标注） | 11.2% / 9.6% | 0:0；对方 93% min_pair 聚集存疑；rating 1158→1159 |
| 70 | 14:57 | v4.3 ver45 | 张原硕(1064) | 0:0 平 | 1（踢球前触球） | 56.0% / 28.0% | 低位密集两次 0:0；rating 1159→1155 |
| 69 | 14:58 | v4.3 ver45 | 你美式吧(911) | 1:0 胜 | 0 | 13.1% / 14.9% | 1:0；对方 7 罚+24 次无效球；rating 1155→1162 |
| 72 | 16:02 | v4.4a ver46 | 112321312312(939) | 1:1 平 | 3（1 踢球前+2 未标注） | 65.4% / 18.3% | rating 1170→1161 |
| 73 | 16:02 | v4.4a ver46 | 蓝色禁区(943) | 5:0 胜 | 1（踢球前） | 2.5% / 29.9% | rating 1162→1170 |
| 74 | 16:02 | v4.4a ver46 | 初号机(995) | 3:3 平 | 1（R-07） | 45.6% / 12.6% | rating 1172→1165 |
| 75 | 16:02 | v4.4a ver46 | 如果以后(1029) | 2:0 胜 | 4（全 R-07） | 58.1% / 23.5% | rating 1161→1172 |
| 76 | 16:15 | v4.5 ver47 | 蓝色禁区1(995) | 6:0 胜 | 0 | 0.0% / 26.0% | rating 1173→1183 |
| 77 | 16:15 | v4.5 ver47 | lhz(958) | 3:0 胜 | 0 | — / — | 归档缺失→无效；rating 1165→1173 |
| 78 | 16:15 | v4.5 ver47 | 如果以后(1005) | 3:0 胜 | 4（2 R-07） | 50.2% / 6.8% | rating 1183→1193 |
| 79 | 16:15 | v4.5 ver47 | 123213(1285) | 0:2 负 | 8（4 R-07） | 73.5% / 19.8% | rating 1193→1180 |
| 80 | 16:39 | v4.5b ver48 | 0707(1055) | 1:0 胜 | 0 | 53.5% / 12.0% | rating 1203→1213 |
| 81 | 16:39 | v4.5b ver48 | 蓝色禁区1(995) | 5:0 胜 | 0 | 0.0% / 18.5% | rating 1187→1195 |
| 82 | 16:39 | v4.5b ver48 | lhz(958) | 3:0 胜 | 0 | — / — | 归档缺失→无效；rating 1180→1187 |
| 83 | 16:39 | v4.5b ver48 | 112321312312(971) | 5:1 胜 | 1（踢球前） | 27.1% / 6.7% | rating 1195→1203 |
| 84 | 16:55 | v4.5b ver48 | 如果以后(1005) | 1:0 胜 | 1 | 42.3% / 13.2% | rating 1226→1234 |
| 85 | 16:55 | v4.5b ver48 | 蓝色禁区(917) | 5:0 胜 | 0 | 1.1% / 20.3% | rating 1220→1226 |
| 86 | 16:55 | v4.5b ver48 | 你美式吧(894) | 0:0 平 | 0 | 12.3% / 41.2% | rating 1234→1221（低段平局 −13） |
| 87 | 16:55 | v4.5b ver48 | Diego(1069) | 3:0 胜 | 0 | — / — | 归档缺失→无效；rating 1213→1220 |
| 88 | 17:14 | v4.5b ver48 | 0707(1055) | 2:0 胜 | 0 | 36.7% / 13.0% | rating 1240→1248 |
| 89 | 17:14 | v4.5b ver48 | 蓝色禁区1(995) | 5:0 胜 | 0 | 0.0% / 19.1% | rating 1227→1234 |
| 90 | 17:14 | v4.5b ver48 | lhz(958) | 3:0 胜 | 0 | — / — | 归档缺失→无效；rating 1221→1227 |
| 91 | 17:14 | v4.5b ver48 | 112321312312(971) | 3:1 胜 | 1 | 30.8% / 21.5% | rating 1234→1240 |
| 92 | 17:33 | v4.5b ver48 | 0707(1055) | 0:0 平 | 0 | 30.4% / 17.8% | 最后3场 1/3；rating 1248→1237 |
| 93 | 17:53 | v4.5b ver48 | 蓝色禁区1(995) | 4:0 胜 | 2 | 0.0% / 17.6% | 最后3场 2/3；rating 1237→1244 |
| 94 | 18:08 | v4.5b ver48 | 如果以后(1005) | 5:0 胜 | 0 | 32.2% / 26.1% | 最后3场 3/3；终局 rating 1244→1251 |

## 13. v5.0 候选（离线准备，credits=0，不下单/不提交线上）

2026-11-24 晚：按 `docs/kb/reviews/v5-spec.md`（analyst da35a69）在分支 `v5` 从 v4.5b（ef64d23）开始实现；main 保持 v4.5b 不动。

### 13.1 Step1 = Lever A 前场推进/射门分区门控
- Z3 贴线/贴底（`|ball.y|>4.20` 或 `ball.x>6.40`）：不射门，沿长轴推 1.5m、power 5.0
- Z1 终结（`d≤6.5`）：power 9.0、瞄远门将侧 ±0.85；射门射线 1.2m 内有对手封堵 → 改推进
- Z2 推进（`6.5<d≤12`）：power 7.0、向门 2.2m、横向避最近对手 1.2m；两侧被封朝中线斜推
- Z2b 远距（`d>12`）：线路 1.5m 内无对手 → 低平 pass 到对方半场边线 power 6.0，否则沿 x 推 2.2m
- A-3.1 卡住回退：前场踢球任务 1.5s 球位移<0.3m → `release_kick()` + 射门冷却 1.0s（交 3s 看门狗）
- 新增参数（param “v5.0 Step1” 段）：FRONT_Z2_MAX_DIST_M=12.0、FRONT_Z2B_POWER=6.0、FRONT_BLOCK_LINE_CLEAR_M=1.2、FRONT_SHOT_COOLDOWN_S=1.0、FRONT_Z3_BALL_X_MARGIN_M=0.60、FRONT_Z3_PUSH_M=1.5、FRONT_Z3_POWER=5.0、FRONT_Z2B_LANE_CLEAR_M=1.5、FRONT_KICK_STALL_S=1.5、FRONT_KICK_STALL_M=0.3
- 门禁：py_compile / check_names / static_check 全绿；replay_playcheck 最近 30 场 **PASS、0 异常**（/tmp/playcheck_v5step1.json）
- 离线候选包：`build/com.example.lqinternalmatch-1.1.0.agent` sha256 `46cee9a2b72deb83d1b9108a1cb1823eed5ac4c6b0b3f0fe3f3d87851aedb0b8`、862871B
- 回放复演（只统计 `_coordinated_kick_plan` 返回动作，#93/#94/#64）：front_push 287/191/64、front_shoot 10/25/12、front_touchline_push 2/77/0、front_pass 0（Z2b 未触发：需 ball>12m 且 x>0，正常）
- 下一步：Step2 = Lever C 反抢（spec §4）；Step3 = Lever B box 终结（spec §3）
