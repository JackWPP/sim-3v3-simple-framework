# v5 A/B 判读口径（预注册）

日期：2026-11-24 晚 | 作者：replay-analyst（离线口径文档，未提交线上）
适用：`v5.0-final`（v5 分支 `705ab48`，候选 sha `2cc3e3b5`）vs 线上 `v4.5b`（main `ef64d23`）
前置：实现评审 `v5-impl-review.md`（3 条 SHOULD-FIX 已在 `705ab48` 修复）、影子评估 `v5-shadow-eval.md`（无阻塞、射门量 ≥25% 下降为最大风险）

> 本文件在 A/B 开跑**前**写定，用于避免「跑完再找指标」。A/B 结果写入 `docs/kb/reviews/v5-ab-results.md`，本口径不随结果修改；如需改判据，单独记「口径修订」并注明原因。

## 1. 设计（最小可判、最省 credits）

- **配对设计**：同对手 2×2，A（v4.5b）与 B（v5）交替跑：`A→0707、B→0707、A→张原硕、B→张原硕`（spec §5.1 的 40 credits 档）。
- **同对手配对失败时**（matchmaking 不命中）：改用「同 rating 段 ±50 的邻近代打」并记录两组对手平均 rating，判读时按对手强度校正方向（强对手下 v5 应更好，弱对手下 v5 至少不差）。
- **样本量**：每组 ≥2 场有效场；若判为 INCONCLUSIVE 可追加 2 场（需 Lead/credits 批准）。**禁止用单场结论**。
- **评分口径**：以「机制是否按预期生效 + 纪律是否破线 + 产出是否可接受」三闸门判定，不单看胜负（胜负受对手/乌龙/掉线污染）。

### 1.1 预算档位（credits 不足时的降级口径）

本文件 §1–§8 是 **A 档（40 credits，4 场）** 与 **B 档（150–250 credits，farm 续跑）** 的执行主体。credits=0 期间已预注册 **A-mini 降门槛档**：`docs/kb/reviews/v5-ab-mini-readout.md`（20 credits、2 场 0707 同对手配对，仅作 smoke/prescreen；B 出现射门归零→ITERATE，出现策略罚单/stuck→ROLLBACK，其余→升级 A 档）。A-mini 结论**不得**直接判 KEEP；三档的包轮换、判读产出物与回退步骤见该文件 §0–§5。

## 2. 有效场判定（violation 记录，不计入胜负/产出对比，但机制指标保留）

1. sha/帧完整性通过（manifest + segments 齐全，`replay_playcheck` 0 异常）。
2. 对手**有效参赛**：away 三台「全静止帧占比」≤85%，且（away ball_touch 事件 ≥5 或 away≥2 台在界外帧占比 ≤50%）；若对手 park/掉线（如 #45 b7ed0d18、#63b9f73e、yzy_7877 的两台 AFK）→ `invalid:opponent_park`。实测脚本 `/tmp/ra/ab_valid.py` 已用 #45/#63b9f73e（INVALID）与 abb37886（VALID）自检。
3. 无**平台级冻结**：事件序列中相邻事件间隔 >20 s、且前一事件 `game.setPlay == NONE && stopped == False`（活球期裁判/引擎卡住，如 #50 的 19 s 球出界不重启）出现 ≥2 次 → `invalid:platform_freeze`。
4. **重启停滞（不是 invalid，记录并两侧对比）**：set-play start → 下一次 `ball_free` >20 s（由裁判 secondary 45 s 兜底自动放开；本基线里张原硕 0:0 两场各 9 段/405 s，属双方都不触球的 gameplay 停滞，48 s「摆球后无人触球」这一类不计平台冻结）。统计 `stall20_episodes/stall20_seconds`；若单臂停滞秒数 ≥另一臂 2× 或 ≥200 s，最终结论标 `context_bias` 并用「非停滞时间」口径复核 G2/G3。
5. 我方无早期事故：开场 60 s 内 inactiveRobot/fallenRobot/乌龙 ≥2 次 → **标记但不剔除**（属纪律证据，归入门禁）。

**口径修订说明（A/B 开跑前，2026-11-24）**：原 §2 把「48 s 摆球后无人触球」也算平台冻结并会判 invalid；实测 v4.5b 张原硕 0:0 基线（两场各 9 段/405 s）会被整场判无效、导致配对臂不可用。现区分「平台/裁判卡住」（invalid）与「重启没人触球停滞」（记录+对比），否则 A/B 无法判读；此为开跑前校准，双方同口径。

## 3. 指标与数据来源

| 层 | 指标 | 定义/来源 | 基线（v4.5b） |
|---|---|---|---|
| 主产出 | shots/场 | rep `shots` 条数（世界球速跃升+距离过滤） | **9.1**（12 场均值，中位 10.0；competitive 8 场 9.9；vs 0707 11.3；vs 张原硕 7.0） |
| 主产出 | 射正/场 | rep `shots[].on_target` | **4.1**（中位 5.0；competitive 2.9；vs 0707 1.0；vs 张原硕 1.0） |
| 主产出 | goals/场、goals/shot | 比分 + rep | **3.0 球/场、goals/shot 0.34**（competitive 2.1/0.21；失球 0.17/场；vs 0707 1.0 球、0.09；vs 张原硕 0 球） |
| 次产出 | box touch/场 | box.txt（球在对方禁区且我方距球≤0.7 m 段数） | **6.6**（中位 6.5；competitive 3.9；vs 0707 1.7；vs 张原硕 0.5；阈值 ≥4 应相对 competitive 基线看） |
| 次产出 | prog travel | 影子报告/`top_analyze2.py` 的 1.5 s 球位移中位 | 1.90 m（阈值 ≥1.20） |
| 次产出 | touch-to-shot% | 触球后 5 s 内射门/触球 | 7.5%（阈值 ≥8%，注意基线已略低） |
| 次产出 | oobCaused/场 | manifest `lastTouchSide=home` 的 throw_in/goal_kick/corner setup 数 | **15.6**（中位 18.5；competitive 8 场 22.0；vs 0707 24.7；vs 张原硕 14.5） |
| 次产出 | press recovery | 丢球后 ≤3 s 夺回占比/中位 | 65.6% / 0.82 s（阈值 ≥60% / ≤0.9 s） |
| 次产出 | 球己方半场占比 | rep ball_zone | **22.2**（competitive 33.2；vs 0707 40.2；vs 张原硕 49.9；目标 ≤55 且不高于同对手基线 +10pp） |
| 纪律门 | R-06/R-07/M-02/inactive/fallen/global_game_stuck | manifest events/fouls | **硬门：0 为优；≥1 要归因** |
| 机制 | Lever A/C/B 触发 | 离线 shadow_eval2 在 A/B 归档上复演两版（shot plan 数、z3 次数、box2 帧、press 帧） | — |

采集命令（每场跑完立即）：
```bash
python3 /tmp/ra/v42/... 2>/dev/null || true   # 旧脚本按需
python3 tools/replay_playcheck.py <manifest>  # 完整性/异常
python3 - <<'PY'  # 或直接用 s6 汇总脚本
PY
```
实际使用：`/tmp/ra/s6_report.py`（playbook §6 表）+ `/tmp/shadow_eval2.py ef64d23|705ab48 <out> <uuid>`（机制触发/决策 diff）+ `analyze2.py`（`oobCaused/shots/goals/penalties`）。

### 3.1 v4.5b 基线实测（A/B 开跑前填充，2026-11-24）

数据源：v4.5b 期 12 场有效归档（#80/#81/#83–#86/#88/#89/#91–#94；#82/#87 归档缺失，#90 lhz 归档缺失）；`analyze2.py` + `box_metrics.py` + manifest `outcome.lastTouchSide`。

| uuid | 对手(档) | 比分 | shots | 射正 | box touch | 球己方半场% | 我方控球% | oobCaused |
|---|---|---|---|---|---|---|---|---|
| abb37886 | 0707(1055) | 1:0 | 11 | 0 | 1 | 53.5 | 38.2 | 23 |
| 82d9be08 | 0707(1055) | 2:0 | 12 | 1 | 2 | 36.7 | 41.6 | 25 |
| 95e8615e | 0707(1055) | 0:0 | 11 | 2 | 2 | 30.4 | 45.3 | 26 |
| bfdd4063 | 蓝色禁区1(995) | 5:0 | 7 | 6 | 11 | 0.0 | 100.0 | 2 |
| 3924e8c1 | 蓝色禁区1(995) | 5:0 | 6 | 5 | 16 | 0.0 | 100.0 | 2 |
| f679fe57 | 蓝色禁区1(995) | 4:0 | 8 | 6 | 9 | 0.0 | 47.8 | 4 |
| 40020243 | 蓝色禁区(917) | 5:0 | 9 | 9 | 12 | 1.1 | 100.0 | 3 |
| d68aac9b | 1123…(971) | 5:1 | 12 | 5 | 13 | 27.1 | 25.1 | 20 |
| 0d64935c | 1123…(971) | 3:1 | 13 | 6 | 13 | 30.8 | 39.1 | 17 |
| 18340da2 | 如果以后(1005) | 1:0 | 8 | 4 | 0 | 42.3 | 28.4 | 21 |
| 0ab411d9 | 如果以后(1005) | 5:0 | 11 | 5 | 6 | 32.2 | 27.6 | 12 |
| 3175346d | 你美式吧(894) | 0:0 | 1 | 0 | 0 | 12.3 | 52.1 | 32 |

参考（A/B 另一配对对手，非 v4.5b）：`6b76306f` 0:0 张原硕（shots 6 / 射正 0 / box 1 / ballH 43.7 / poss 73.8 / oob 14）；`cebfeee4` 0:0 张原硕（v4.3；shots 8 / 射正 2 / box 0 / ballH 56.0 / poss 71.6 / oob 15）。

**汇总**
- 全量 12 场：10 胜 2 平、36:2；shots **9.1**（中位 10.0）、射正 **4.1**（中位 5.0）、goals **3.0**/场、goals/shot **0.34**、box touch **6.6**（中位 6.5）、球己方半场 **22.2%**、oobCaused **15.6**（中位 18.5）。
- **竞争性子集 8 场**（排除 3 场对手控球 0 的 bfdd4063/3924e8c1/40020243）：shots **9.9**、射正 **2.9**、goals **2.1**、box touch **3.9**、球己方半场 **33.2%**、oobCaused **22.0**。
- **0707 子集 3 场**（A/B 配对对手）：1:0 / 2:0 / 0:0；shots **11.3**、射正 **1.0**、goals **1.0**、box touch **1.7**、球己方半场 **40.2%**、oobCaused **24.7**。（我方对 0707 射正率仅 8.8%，是 v5 最该改善的点。）
- **张原硕子集 2 场**（0:0×2）：shots **7.0**、射正 **1.0**、goals **0**、box touch **0.5**、球己方半场 **49.9%**、oobCaused **14.5**。

**G2/G3 阈值校准（按 §4 公式代入）**
- G2 总体：射正 ≥ **3.1**（max(2.5, 4.1×0.75)）、goals ≥ **2.25**/场、shots ≥ **5.9**（9.1×0.65）。
- G2 vs 0707：射正 ≥ **2.5**、goals ≥ **0.75**/场（2 场 ≥2 球）、shots ≥ **7.3**。
- G2 vs 张原硕：射正 ≥ **2.5**、goals **>0**（2 场至少 1 球，基线 0 故用绝对下限）、shots ≥ **4.6**。
- G3 校准：box touch ≥4（competitive 基线 3.9，合理）；oobCaused **不高于同对手基线 +10%**（vs 0707 ≤27、vs 张原硕 ≤16、competitive 参考 ≤24）——**§4 原写「≤15」低于 v4.5b 自身 competitive 水位（22.0），直接套用会把「正常 v4.5b 水平」误判为回退，特此按实测校准**。
- 球己方半场：总体 ≤55%（v4.5b 全量 22.2% 被 farm 拉低，competitive 33.2%；A/B 以同对手基线为准，vs 0707 目标 ≤50%、vs 张原硕 ≤60%）。

**注意**：全量 12 场中 3 场对手几乎不触球（bfdd4063/3924e8c1/40020243，对方控球 0%），把全量均值抬高（shots +1~2、box +2~3、goals +0.5+）；A/B 判读以「同对手子集 + competitive 子集」为主，全量仅供版本间趋势参考。


## 4. 三闸门决策规则（pre-registered，阈值按 §3.1 基线校准）

> ITERATE 臂登记：**iter2 = 首选**（`v5.0-iter2-193145a9.agent`，sha `193145a9…`，候选已推送；shadow 全归档 92 场见 `v5-shadow-allsets.md`）；iter1 留档（+5% 不足）。A/B 触发 ITERATE 时的验证规模=**2 场同对手配对**，预算合计 **60 credits**（4 场主 A/B + 2 场 iter2）。

**G1 纪律（硬门）**
- PASS：A/B 组内策略性罚单（R-06/R-07/M-02/inactive）≤1 且可归因于对手/平台（例如对方快发/掉线冻结），且 fallen/stuck 不高于 v4.5b 近 10 场均值。
- **ROLLBACK**：2 场内 ≥2 张策略性罚单；或 global_game_stuck ≥2 场；或 fallenRobot ≥3 次/场（M-04 被新角色诱发）。

**G2 产出（主判据，对照 §3.1 基线表：同对手子集优先）**
- PASS：射正/场 ≥ max(2.5, 基线−25%) 且 goals/场 ≥ 基线−25%；shots/场 ≥ 基线−35%（允许因少盲射下降，但不能到「无威胁」）。
- 若同对手历史上 v4.5b 都胜 ≥2 球，v5 应至少 1 胜 1 场进球 ≥2；否则视为产出回退信号。
- 离线预判（shadow 全量 92 场，`docs/kb/reviews/v5-shadow-allsets.md`）：final2 射门决策帧 −61%（median 0.33×），**G2 的 shots 项有较大概率触发 ITERATE**；线上以射正/goals 为准（少射多推是否换到更好机会只能由 A/B 判定）。

**G3 效率/地盘（辅助，防止「为改而改」）**
- PASS：box touch ≥4/场（competitive 基线 3.9）、prog travel ≥1.5 m、oobCaused ≤同对手基线+10%（§3.1 校准，替代原「≤15」）、press recovery ≥60%。
- 允许单项略低，但不得同时两项低于基线。

**决策矩阵**
| G1 | G2 | G3 | 判定 |
|---|---|---|---|
| PASS | PASS | PASS | **KEEP v5**，按 §7 继续下一轮 |
| PASS | FAIL（射门/射正/goals 下降 >25%） | PASS 或改善 | **ITERATE（v5 内放宽 Z1 → 用 iter2，优先）**：iter2 已把 shadow 射门缺失从 −61% 收敛到 −48~56%、z3 误判修复，参数=①Z1 封线否决仅 `d_goal>4.5 m` 或最近阻挡者距球 <0.6 m 时生效；②Z3 收窄为 `|y|>half_w−0.15 且 x>half_l−1.0`；③cooldown 0.6 s。iter1（封线 1.2→0.9+cooldown 1.0→0.6）仅 +5% 已留档，不再作为 ITERATE 臂。验证：用 iter2 做 **2 场同对手配对**（与主 A/B 同对手/同槽位），按本表 G1/G2/G3 复判；**总预算 60 credits = 4 场主 A/B + 2 场 iter2**。 |
| PASS | FAIL（下降 >50%） | FAIL | **ROLLBACK 回 v4.5b**（控制包 sha `6fb30100` 系），记录原因与场次；若已跑 iter2 且 iter2 仍 FAIL，则回 v4.5b 并登记「v5 机制方向不适用于当前对手池」 |
| FAIL | — | — | **ROLLBACK 或先修**（若单张可归因对手导致，可再跑 1 场确认） |
| 混杂 | — | — | **INCONCLUSIVE**：追加 2 场（需批准） |

## 5. 归因要求（避免把噪声当机制）

- 每个失球/进球标注：我方失误、对方乌龙、对方掉线/park、定位球二次进攻、纯运气（折射/门将失误）；与 v4.5b 同对手历史逐球对比。
- **机制核验双轨**：线上 action 标签会被 `attack()` 末尾覆盖为 `attack:kick`（影子报告 §5.3）；必须用离线 shadow_eval2 在 A/B 归档上跑两版，比较 `shoot_9/push_7/z3_5` 计划数、`support:box2_*` 与 `press:*` 帧数，确认「机制确实在 A/B 场次触发且按预期生效」；若某机制 0 触发 → 该机制视为未验证，不能计为收益。
- 若出现新形态罚单（如 press 追线外球、box2 久站、Z3 把球推回自半场），对照 `v5-impl-review.md` 的 SHOULD-FIX 回归清单（box2 2 s 回退、press 场内门控、recover 力度下限）逐条核验 `705ab48` 修复是否生效。

## 6. 风险与限制（来自影子报告 §5 + 本节补充）

1. **射门量风险**（最大）：前场射门计划 −60%（2046→818/10 场），touch-to-shot 基线 7.5% 已低于 8% 阈值；A/B 必须重点看 shots/射正/goals，下降 >25% 即 ITERATE。
2. **贴线长轴推 320 次/10 场**：可能形成「推来推去不射」；看 box touch 与 z3 后 5 s 球是否进禁区。
3. **标签不可归因**：线上只能看到 `attack:kick`；依赖离线复演。
4. **风险代理非纪律证据**：R-06/R-07 代理两版一致只说明「同位置无更危险动作」，最终以官方罚单为准。
5. **回放分布偏 farm**：影子 10 场 6 场低段，v5 在高强度对抗的收益可能被低估、风险也可能被低估（A/B 配对随机性）。
6. **n=2/组功效低**：结论按「闸门 + 方向一致」判，不追求统计显著；INCONCLUSIVE 时追加场次而不是强行二选一。
7. **平台异常**（48 s 冻结、球出界未判、并发启动慢）会污染产出与纪律计数，必须按 §2 标记。

## 7. 通过后下一轮（不在本口径强制）

v5 KEEP 后，下一轮优先级建议（供 Lead 选）：
1. Lever A 射门量放宽/二次进攻：Z1 被封堵时改「回做给 box2/边路再传」而不是硬推回中场。
2. box2 预置改为「后点 + 门前 1.4 m 双点」按球侧选择，减少后点空等。
3. 若 A/B 显示 box touch 提升但 goals 未升 → 终结质量（瞄准/挑射/补射时机）优先级高于继续加机制。

## 8. 回滚与记录

**A/B 候选包登记（开跑前）**：实验包 `build/candidates/v5.0-final2-172da34d.agent`（866,437 B，`sha256 172da34d7c82…18338`；cleanup `8448016` 行为中性，已复核 PASS）；控制包 `v4.5b-6fb30100.agent`；A/B 代码基线 `705ab48`（= `15090f0` 代码树）；4 场配对贯穿同一实验包 sha。机制归因优先用线上 action 计数（cleanup 后机制标签可见），并用离线 `shadow_eval2.py` 双版 diff 交叉核对。

- 回滚候选：`v4.5b` main `ef64d23`（候选 sha 以 `build/candidates/` 记录为准）。
- A/B 场次在 `records.md` 标记 `[A/B]`，不参与 rating 趋势拟合（rating 波动本身也记录）。
- 结果与判定必须同时写：原始指标表、逐球归因、机制触发证据（离线 diff）、最终 KEEP/ITERATE/ROLLBACK 及依据条目。

---
评审依据：`docs/kb/reviews/v5-spec.md`、`v5-impl-review.md`、`v5-shadow-eval.md`（影子报告数据）、`docs/kb/online-loop.md` §14。
