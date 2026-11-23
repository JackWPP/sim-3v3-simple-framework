# 线上对局迭代记录（3v3 FREE_BATTLE，10 场冲刺）

目标：在 champion.booster.tech Arena 3v3 跑满 ≥10 场有效对局（finished + 回放归档），
每场由 replay-analyst 深度复盘（胜局同样复盘），按建议小步改策略（每轮 1-2 处），
离线构建 .agent → 提交线上默认代码 → 继续下一场。

起点：线上默认代码 version 10 = v2.5（sha256 20d0965f…，836697B），仓库 HEAD=671af83。
每场 10 credits。有效场次判定：match state=finished 且 `tools/online_match_fetch.py` 回放已归档。

## 汇总表

| # | 时间(本地) | 版本 | 对手 | 对手rating | 比分(我:敌) | 我方罚单 | 对方罚单 | 关键事件 | 本轮调整 | 复盘文件 |
|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 2026-11-23 16:03 | v2.5 (ver10) | w未来希望 | 1141 | 1:2 负 | 3（合计 90s，全为 3×stopped_motion：robot2@sim204.5s 0.330m、robot2@sim521.1s 0.301m、robot3@sim669.8s 0.303m，阈值 0.3m） | 10（5×illegalPosition、4×defender_set_play_interference、1×fallenRobot） | 我方进球 466.3s；失球 230.1s（对方 throw-in 后我方第一脚短传选中被罚下的 robot3，落点 (-5.8,3.0) 朝己门、固定 3.6 力度滚 8.2m **自摆乌龙**）、713.0s（终场前 8.5s 绝杀，门将 guard:clear 漂离门线）；set_play_retake 11 次（全为我方定位球：4×对方提前触球、5×对方 free_kick_avoidance 重踢、2×我方第一脚 ball_out）；对方 531.9s 进球被判 disallowed_indirect（无效，球权归我方）；协同：min_pair<1m 4.7%（历次最好）、ball_in_home_half 54.2%（v2.3 24.2%，中场失控）；回放 73 段 sha256 73/73 校验通过、6207 帧；rating 1209→1156 | v2.6（按 analyst+Lead）：①stopped 宽限后全员显式 stop + 0.35s 延迟补偿 + 窗口 0.35s/速度 1.0/仅非门将撤离；②set_play 短传只选 active 队友、落点禁止朝己门、力度按距离 clamp(3.0+0.25d,3.0,4.5)；③主罚改选「到球后方 1.0m 接近点最近」者（排除门将）+ 粘滞 | docs/kb/reviews/20c6a6cb-3399-4072-b89c-ff791740201a.md |
| 2 | 2026-11-23 16:40 | v2.6 (ver11) | 大魔王 | 1206 | 1:1 平 | 0 | 1（illegalPosition: kickoff_kicking_side_outside_center） | 我方进球 sim 533.8s、对方 sim 463.3s；**sim 228.96s 我方 throwIn 第一脚（robot2，唯一 ball_touch 224.88s）直接进网 → goal_disallowed_indirect，白丢 1 球**；retake **0**（v2.5 为 11）、罚单 **0**（v2.5 为 3）→ v2.6 两项 P0 达成；协同 min_pair<1m 11.9%（v2.5 4.7% 回升）、ball_in_home_half 48.9%、avg_nearest 2.71；回放 71 段 sha 71/71、6076 帧；评分 1156→1161 | v2.7（按 analyst+Lead）：①stopped 窗口后 0.12m/s 径向慢爬（R-07 豁免 + 2s 0.24m <0.3m）②guard:clear 方向固定朝对方半场、站位 x clamp ≥-(half_l-KEEPER_LINE_INSET_M)③踢球对齐门控 + KICK_ENTER 1.0/EXIT 1.6④间接球第一脚短传避开对方门线 2m 与射门线 | docs/kb/reviews/dffb89db-7e6a-414d-849c-fc074102dfe9.md |
| 3 | 2026-11-23 17:07 | v2.7 (ver12) | 群玉阁 | 1155 | **0:6 负** | 3（2×fallenRobot：robot2@sim75.5、robot3@sim358.2，三台挤同一落点互撞；1×stopped_motion：robot2@sim140.6 移动 0.332m/2.9s，v2.7 慢爬 0.12m/s 跨过 1.5s 静止宽限） | 3（1×defender_touched_before_kick + 2 张） | **回归场**：kick 尝试 105 次成功 49%（v2.6 85/59%）、kick 活动帧减半——v2.7 ③ 对齐门控反复起停导致进攻瘫痪；我方触球 24（自家三区 16、对方三区 **0**）、射门 5 次全为 8–13.7m 弱射、0 进球；球在己方三区 **70.5%**、min_pair<1m **19.7%**；6 个失球全在 PLAYING 自家半场，其中 5 球前一刻「球静止 2–3s + 我方最近人 0.59–1.03m 不动」；52.44s 我方门球第一脚从 (−6.00,−2.00) 横穿自家门口到 (−6.97,2.18) 送对方角球；retake 2；回放 69 段 sha 69/69、5854 帧；rating 1161→1124（**根因更正**(analyst 离线复现)：主因非对齐门控，而是 v2.7 引入的 _act_normal presser 分支 NameError（裸 `ball`）→ 球一停每帧抛异常、runtime 捕获后全员 stop → 全队冻结；对齐门控是次要回归，已回退） | **v2.8**：①回退 ③（KICK_ENTER 2.0/EXIT 2.5、撤对齐门控）；②保留门将 clamp/clear；③修 ①：STOP_VACATE_WINDOW_S 0.35→1.15、crawl 0.12→0.0、窗口后硬停（M-02+R-07 同时归零）；④限缩 ④：横向轻推仅 ball.x>-2，己方三区改朝前 2m+同侧轻推 | docs/kb/reviews/60d19472-7d55-4675-a750-1bf06e21e215.md |
| 4 | 2026-11-23 17:33 | v2.8 (ver13) | 高考加油 | 1217 | **0:6 负** | 7（**全部 inactiveRobot**：robot1@sim305.3、robot2@sim306.2、robot2@sim494.5、robot3@sim494.7、robot3@sim552.2、robot1@sim553.9、robot3@sim637.3；evidence: inactiveDuration 40、ballDistance 0.316m≤3m） | 2（1×Illegal position robot5@277.6 robotX=−6.977；1×Fallen robot robot4@500.7 upDot 0.036） | **开球期非主罚 stay 站桩**：282.6s 我方开球 phase 起 robot1 停在我们开球 READY 槽位 (-0.66,3.83)，286.1s 主罚触球后球滚到 (-0.45,3.60) 停在其脚边 0.31m，294–305s 三台几乎无 move/kick 指令（move.active=false），10s 后 robot1/robot2 相继吃 inactiveRobot；294–305s 内 away robot4 也在球旁 0.9m 静立（对方未吃罚单，判罚只针对球所在半场方）；失球 sim 55.5/105.4/254.7/408.1/500.5/638.8（全 away）、我方 0 进球；协同 min_pair<1m 14.6%、ball_in_home_half **86.2%**、avg_nearest 2.03（对方 pair 5.93/min 7.8%）；retake 0；回放 68 段 sha 68/68、5788 帧；rating 1124→1098（**根因更正**：7 张 inactiveRobot 与 288–305s 三台无 move/kick 指令同源于 NameError 全员冻结，非开球期 stay 站桩） | **v2.9**（Lead 批准）：开球期非主罚不再原地 stay——每帧球距自己<3.2m 或球向我方半场滚动(vx<−0.05) → 退到 (-2.5,±2.6)（选离球更远侧；若仍<3.2m 退到 (-4.0,±2.0)）并保持走位，球权开放前不 stop 站桩；其余 v2.8 改动保留 | docs/kb/reviews/f751146f-b14e-4ed8-b6ad-923fd872b4c1.md |
| 5 | 2026-11-23 18:05 | v2.9 (ver14) | 蓝色禁区1 | 1104 | **2:0 胜** | 9（**全部 inactiveRobot**，30s：robot1@53.05、robot2@57.24、robot1@146.50、robot1@238.83、robot1@349.56、robot1@427.56、robot3@503.95、robot1@529.43、robot1@615.75；evidence inactiveDuration 6–44s、ballDistance 1.82–2.87m≤3m、state=playing/setPlay=noSetPlay） | 0 | **v2.9 仍带 NameError（未修）**：开球/活球期多次三台无 move/kick 指令冻结 → 9 张 inactiveRobot；我方进球 sim154.08/250.43；失球 0；retake 0、oob 0/0；协同 min_pair<1m 15.2%、ball_in_home_half 0.0（该场指标异常不可引用）、avg_nearest 4.98（away pair 1.33/min<1m 83%，对方更挤）；回放 64 段 sha 64/64、5643 帧；评分 1098→1133（+35）；**按 Lead m01226 记为无效场次/不作迭代依据**（bug 所致，非策略效果） | **v2.10**：①修 `_act_normal` presser 分支 NameError（补 `ball = context.ball`；全局 grep 其余 v2.7+ 裸 ball 已排查）②防御性 data-loss 修复（game/ball 丢失时 0.12m/s 慢速巡逻、last_ball_pose 记忆、审计 stop() 兜底）；修复后离线回放自检 0 异常再 build/submit | docs/kb/reviews/9d0d2d4c-12c0-4204-8246-d96c9acd4671.md（1 行结论 + bug 证据；本场不作为迭代依据） || 6 | 2026-11-23 18:31 | v2.10 (ver15) | 马里奥冲压 | 1215 | **1:2 负** | 0 | 0 | 我方进球 sim10.2s；失球 sim116.2s/590.1s；**双方 0 罚单、retake 1**；协同 min_pair<1m 9.1%、two<1.5m 6.2%、avg_nearest 2.91、ball_in_home_half 54.1%；oob awarded 21/caused 11；73 段 sha 73/73、6353 帧、724.1s；rating 1133→1109（-24）；**v2.10 带 `_act_opp_kickoff` store NameError（每个对方开球相位冻结 1–10s）→ 按 Lead 记「半有效」仅作观测，不作策略迭代依据** | **v2.11**：①修 `_act_opp_kickoff` 缺 store 形参（调用处传 store）②新增静态门禁 tools/static_check.py（调用参数/自由名检查）③回放门禁 tools/replay_playcheck.py 设为提交前必跑（10 场 0 异常） | docs/kb/reviews/f751146f-b14e-4ed8-b6ad-923fd872b4c1.md（第 4 场复盘，供根因对照） |

## 提交门禁（v2.11 起，每次 build/submit 前必跑）

v2.5–v2.10 连续踩到「静态可查、线上才爆」的 NameError（v2.5 `_act_opp_kickoff` 缺 `store` 形参；
v2.7 `_act_normal` presser 分支裸 `ball`），两次都被 framework `runtime._loop` 捕获并对全员
`p.stop()` → 全队冻结。今后提交前固定两步，任一失败不得 submit：

1. 静态门禁：`python3 tools/static_check.py`（必须 STATIC_CHECK_OK）
   - 规则①：模块级函数调用参数个数/关键字与定义不匹配（多传/少传/未知关键字/重复赋值）
   - 规则②：函数/lambda 体内自由名（如 `store`/`ball`）未在参数/局部/module 全局/builtins 定义
   - 回归验证：`python3 tools/static_check.py --git-ref 5f60659` 应报 3 条 FAIL（ball×2 + store×1）
2. 回放门禁：`python3 tools/replay_playcheck.py <10 场 uuid...> --json /tmp/playcheck_latest.json`
   （必须 10/10 PASS、play() 0 异常；真实回放帧逐帧重建 Context，含 OPP_KICKOFF 等相位）

辅助：`python3 -m py_compile src/main.py src/player.py src/param.py` + `python3 tools/check_names.py`（CHECK_OK）。
