# S2 官方赛段计划（v5 切换与免费验证通道）

日期：2026-11-24 | 作者：Lead（离线计划，未动 src/线上默认）
适用：credits=0 期间，用官方赛段（免费）替代付费竞技场做 v5.0 验证与冲榜。

## 1. 赛段日程（北京时间 = UTC+8）

| 阶段 | 开始 | 结束 | 轮次 | 备注 |
|---|---|---|---|---|
| 资格赛 QUALIFY | 11-14 17:00 | **11-28 23:59** | — | 已 QUALIFIED（AI_WIN + 竞技场豁免 42 胜） |
| 预选赛 SWISS | **11-29 23:59** | 12-01 23:59 | 15 轮 | 瑞士轮，前 64 进小组赛 |
| 小组赛 GROUP | 12-05 00:00 | 12-07 23:59 | — | 16 组×4 队单循环，前 2 出线 |
| 淘汰赛 KNOCKOUT | 12-08 00:00 | 12-13 23:59 | — | 32 强单败，平局金球加时 |
| 颁奖 AWARDS | 12-12 23:59 | — | — | — |

数据源：`GET /api/v1/competition/seasons/s2/overview`（2026-11-24 复查，teams_count=2919、matches_count=1737）。

## 2. 关键机制（待首场官方赛实测确认）

1. 官方赛**不消耗 arena credits**（待确认：首场前后查 `/credits/balance` 差值应为 0；arena 自由对战仍是 10/场）。
2. 官方赛由系统按赛段排期自动配对，`/seasons/s2/teams/me/next-match` 在赛段开始后应返回对手；当前为 null（未开赛）。
3. 对局使用**开赛时的默认代码版本**（FAQ：比赛中代码锁定、中途不能换；赛前可换）→ 赛段间切换默认版本是合法且唯一的「上线验证」手段。
4. 官方赛有结果/replay（`source=OFFICIAL`、`/matches/{uuid}/result-jsons` 有正式结果 JSON），可用现有工具归档复盘。

## 3. 计划：用 SWISS 做免费 v5 验证（不花 credits）

### 3.1 赛前（现在 ~ 11-29 23:59）
- 默认保持 **v4.5b（version 48）**，避免无验证下换线上默认。
- 若用户充值 → 先跑 A-mini（20 credits，2 场）或 A 档（40 credits）出结论，再决定 SWISS 用哪版。

### 3.2 SWISS 开赛后（无充值时的自主方案）
- 每轮开赛前 5 分钟检查 `next-match`；用 `tools/ab_runner.py status` 确认当前默认。
- **第 1–2 轮用 v4.5b（控制）**：记录官方赛基线（比分、shots/射正、纪律、球半场占比）。
- **第 3 轮起切 v5.0-final2**（`tools/ab_runner.py set_default build/candidates/v5.0-final2-172da34d.agent --display-name com.example.lqinternalmatch-v5.0-final2`，0 credits）。
- 每场结束立即归档（`tools/online_match_fetch.py` + `tools/online_replay_analyze.py` + `/tmp/ra/ab_row.py`），写入 `docs/kb/online-matches/records.md`。
- **回滚规则（预注册）**：v5 连 2 场出现 ≥2 张策略罚单（R-06/R-07/M-02/inactive）或 2 场共失 ≥6 球且 0 进球 → 立刻切回 v4.5b；若首 3 场 v5 拿分 ≥ v4.5b 基线（同阶段对手强度校正），则保持 v5。
- SWISS 结束后按结果决定 GROUP/KNOCKOUT 用哪版；任何时候保持可回滚（v4.5b 包与提交记录都在仓库）。

### 3.3 监控脚本（新增，待实现）
- `tools/swiss_watch.py`：赛段窗口内每 60s 轮询 `next-match`；发现 match → 校验默认版本（可配置期望版本 id/sha）→ 等待 finished → 自动 fetch/analyze/追加 records → 发钉钉/日志摘要（无外部服务，写 `docs/kb/online-matches/swiss-log.md`）。
- 触发条件：`seasons/s2/overview.current_phase == SWISS` 且 `next-match != null`。

## 4. 风险

- 无 A/B 就切 v5 属于「官方赛免费样本验证」，样本噪声大（15 轮、对手强）；已用预注册回滚规则控制。
- 官方赛对手强（玩家 pool 2919 队），v5 的「少射多推」可能放大弱点；v4.5b 是已验证基线。
- 若用户中途充值，优先走 A-mini/A 档正式 A/B，再进官方赛。

## 5. 待确认清单（首场官方赛后回填）
- [ ] 官方赛扣 credits 吗（balance 前后）
- [ ] 比赛需手动开始还是自动开始
- [ ] 默认代码是开赛快照还是提交时快照
- [ ] 官方赛 replay/result 是否与 FREE_BATTLE 同 schema（result-jsons 已有正式结果）
