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
| 2 | 2026-11-23 16:40 | v2.6 (ver11) | 大魔王 | 1206 | 1:1 平 | 0 | 1（illegalPosition: kickoff_kicking_side_outside_center） | 我方进球 sim 533.8s、对方 sim 463.3s；**sim 228.96s 我方 throwIn 第一脚（robot2，唯一 ball_touch 224.88s）直接进网 → goal_disallowed_indirect，白丢 1 球**；retake **0**（v2.5 为 11）、罚单 **0**（v2.5 为 3）→ v2.6 两项 P0 达成；协同 min_pair<1m 11.9%（v2.5 4.7% 回升）、ball_in_home_half 48.9%、avg_nearest 2.71；回放 71 段 sha 71/71、6076 帧；评分 1156→1161 | v2.7（按 analyst+Lead）：①stopped 窗口后 0.12m/s 径向慢爬（R-07 豁免 + 2s 0.24m <0.3m）②guard:clear 方向固定朝对方半场、站位 x clamp ≥-(half_l-KEEPER_LINE_INSET_M)③踢球对齐门控 + KICK_ENTER 1.0/EXIT 1.6④间接球第一脚短传避开对方门线 2m 与射门线 | docs/kb/reviews/dffb89db-7e6a-414d-849c-fc074102dfe9.md（待 analyst 出） |

## 场次明细
