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

## 场次明细
