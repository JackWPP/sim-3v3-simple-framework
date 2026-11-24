# v5 A/B 预算档位与降门槛口径（A-mini / A / B）

> 状态：预注册（开跑前写下、不得事后改判据）。主线口径见 [`v5-ab-readout.md`](v5-ab-readout.md)（40 credits 正式档）；本文件补充 **20 credits smoke 档** 与 **farm 续跑档**，供 credits 不足时降级决策。
> 只写文档；不动 `src/`、不提交线上、不发起挑战。包与 sha 以 `build/candidates/` 记录为准。
> 相关：`v5-spec.md`（机制）、`v5-impl-review.md`（实现审查）、`v5-shadow-eval.md`/`v5-shadow-allsets.md`（离线预判）。

## 0. 通用前置（三档共用）

- **包登记（开跑前核对 sha，不一致不得开跑）**：
  - 控制组 `v4.5b-6fb30100.agent`（v4.5b 终局）。
  - 实验组 `v5.0-final2-172da34d.agent`（866,437 B，`sha256 172da34d7c82…18338`；代码基线 `705ab48`）。
  - ITERATE 臂 `v5.0-iter2-193145a9.agent`（866,946 B，`sha256 193145a9…`；仅 A 档 ITERATE 或 A-mini 触发后用）。
- **每场提交前**：记录 slot 序号、`package_sha`、对手、`player_id`、uuid、时间；提交后核对归档 sha 校验通过（§2 有效场）。
- **纪律判定**：策略性罚单 = R-06 / R-07 / M-02 / inactiveRobot；`global_game_stuck` 或 analysis 中 `stuck` 事件计 `stuck`。可归因平台/对手的按 §2/§4 G1 标记 `context_bias`，不直接计入，但**不得据此把档位结论升级为 KEEP**。
- **禁止**：单场结论直接 KEEP；档内换对手/换包而不重开档；未记录 sha 的场次计入结论。
- **产出**：所有档位结果写入 `docs/kb/reviews/v5-ab-results.md` 对应小节（见各档 §）。

## 1. A-mini（20 credits，2 场）—— smoke / prescreen

**目的**：credits 不足时，用最小样本排除「明显坏」（纪律破线 / 射门归零），不承担正式判读。
**统计功效警告**：同对手各 1 场，胜负、乌龙、掉线、平台冻结噪声都可能主导；此档**只能排除明显坏，不能证明好**。

**配对与包轮换（set_default 序列）**：

| slot | 对手 | 提交包 | 目的 |
|---|---|---|---|
| 1 | 0707（同 §3.1 子集） | `v4.5b-6fb30100.agent`（A） | 同场控制 |
| 2 | 0707（同 slot 1 同槽位） | `v5.0-final2-172da34d.agent`（B） | 实验 |

- 若 matchmaking 未命中 0707：按主 readout §1「同 rating 段 ±50 邻近代打」执行并记录，但 A-mini 不因此升级为正式结论。
- 任一 slot 被 §2 判 `INVALID`：同 slot 补跑一次（+10 credits，需 Lead 批准），不得换对手凑数。

**判定（A-mini 专用，阈值来自 §3.1 0707 基线：shots 11.3 / 射正 1.0 / goals 1.0 / box 1.7 / ballH 40.2 / oob 24.7）**：

- **ITERATE 触发**（满足任一）：
  1. B 的 shots **< 7.3**（即低于 0707 基线 −35%，与 A 档 G2 同阈）；
  2. B 的射正**低于 A**，或 B 射正 = 0 且 A ≥ 1；
  3. B 的 box touch ≤ 0 且 A ≥ 1（前场终结完全消失的 smoke 信号）。
  → 动作：**不再用 final2 继续烧 credits**；若 credits 允许，用 `iter2` 臂再打 **2 场 0707 同槽位配对（+20 credits，共 40）**，判读按主 readout §4 ITERATE 口径；否则带 ITERATE 结论停档。
- **ROLLBACK 触发**（满足任一）：
  1. B 出现 **≥1 张策略性罚单**（R-06/R-07/M-02/inactive）；
  2. B 出现 `stuck`/`global_game_stuck`；
  3. B 的 fallenRobot ≥ 3（M-04 被新角色诱发）。
  → 动作：立即停档，按本文 §4 回退到 v4.5b，记录共 20 credits 花费。若罚单明确可归因平台（见 §2），允许同 slot 重跑 1 场（+10），但结论仍最多 INCONCLUSIVE。
- **INCONCLUSIVE**（未触发以上任一）：A-mini 不判定 KEEP；动作 = **升级到 A 档（40 credits）**，把 A-mini 两场作为第 1 对 0707 的预跑数据并入（不重复花钱），A 档再补 `B→0707`、`A→张原硕`、`B→张原硕` 三场（30 credits），合计 50 credits 完成正式口径；或者若 Lead 要求严格 40，则 A 档重跑完整 2×2（A-mini 两场仅留档）。
- **A-mini 自身不得产出 KEEP/ROLLBACK 正式结论**；产出物 = `v5-ab-results.md` 的 `## A-mini（2 场 smoke）` 小节（原始指标表 + 触发项 + 动作建议）。

## 2. A 档（40 credits，4 场）—— 正式口径

- 设计与判据**完全沿用主 readout §1–§5**（2×2 配对：`A→0707 / B→0707 / A→张原硕 / B→张原硕`；§2 有效场；§3.1 同对手基线阈值；§4 G1/G2/G3 三闸门 + 决策矩阵；§5 归因要求）。
- 包轮换：A 槽 = `v4.5b-6fb30100.agent`；B 槽 = `v5.0-final2-172da34d.agent`；若 A-mini 后直接进入 ITERATE 路径则 B 槽 = `v5.0-iter2-193145a9.agent`（并在结果文档中标注「iter2 臂」）。
- **不得跨档混用**：A 档 4 场必须同包 sha；若中途发现 sha 变化 → 重开档并记录。
- 判定产出：`v5-ab-results.md` 的 `## A（4 场正式）` 小节（原始表 + 三闸门 + KEEP/ITERATE/ROLLBACK/INCONCLUSIVE + 机制触发证据）。
- 决策与回退：按主 readout §4 矩阵；ITERATE → 用 iter2 再做 2 场同对手配对（+20 credits，总预算 60，见主 readout §4 登记）；ROLLBACK → 本文 §4。

## 3. B 档（150–250 credits，16–20 场）—— A/B 通过后冲分

**前置**：A 档（或 A-mini+ITERATE 路径）结论为 **KEEP**；否则不得进入 B 档。
**目标**：按 `/tmp/ra/farm_plan2.md` 与 `farm_plan.md` 的顺序冲 rating，阶段目标 **rating ≥ 1300**（v4.5b 实测 1251；v5 的 gain 来源是夺冠转化）。

**执行**：

- 对手顺序（同 farm_plan2 前 8，每档按 EV/活跃度微调）：0707（1055）→ 蓝色禁区1（995）→ lhz（958）→ 如果以后（1005）→ 112321312312（971）→ 蓝色禁区（917）→ Diego（969）→ 你美式吧（894）。
- 场次与 credits：16 场 = 160 credits；20 场 = 200 credits（均落在 150–250 档）。**每场 10 credits**，按实际余量定 16/18/20。
- 包：保持 A 档 KEEP 的包（final2 或 iter2）**整档不换**；A/B 轮换只存在于 A 档，B 档不轮换。
- 每 4 场做一次滚动判读（rolling checkpoint）：
  1. rating 轨迹（起点/当前/峰值，目标 ≥1300）；
  2. G2/G3 对同对手 v4.5b farm 基线（shots/射正/goals/box/oob）；
  3. 纪律滚动（4 场内策略罚单、stuck、fallen）；
  4. 失败模式归类（若连败/被压半场，记录对手与机制）。
- **停止条件（任一）**：rating 连续 2 个 checkpoint 不升；单 checkpoint rating −40；4 场内 ≥2 张策略罚单；stuck ≥2 场；credits 达到 250 上限。
- 产出：`v5-ab-results.md` 的 `## B（farm 16–20 场）` 小节（逐场表 + checkpoint 表 + 是否达 1300 + 后续建议）。
- 回退：若累计 ≥3 败且 rating 跌破 A 档起点 −40，按 §4 回退 v4.5b 并停档（剩余 credits 交回 Lead 决策）。

## 4. 失败回退到 v4.5b 的步骤（三档共用）

1. **停**：不再提交 v5 包；记录当前档已花 credits 与场次。
2. **切包**：将 default 切回 `v4.5b-6fb30100.agent`，核对 sha（以 `build/candidates/` 记录为准）；不修改 `src/`、不提交线上，只换包。
3. **记录**：在主 readout §8「回滚与记录」与 `v5-ab-results.md` 写：触发条件、场次 uuid、指标、归因、回退包 sha。
4. **确认（可选）**：仅当纪律异常归因不明时，用 v4.5b 打 **1 场**确认场（10 credits，需 Lead 批准）；结果只用于确认环境，不计入 A/B 结论。
5. **通报**：Lead + T1 各一行；T1 按指令 resume farm/baseline 流程。
6. **复盘**：把失败机制归入 `v5-ab-readout.md §6 风险与限制` 或新增 `v5-impl-review.md` 补记，供下一轮 spec 修正（不推翻本轮「机制方向」结论，除非复现 2 次）。

## 5. 档位对比速览

| 档 | credits | 场次 | 包 | 产出 | 允许的结论 |
|---|---|---|---|---|---|
| A-mini | 20（+20 iter2） | 2（+2） | v4.5b / final2（+iter2） | `v5-ab-results.md` §A-mini | 仅 smoke：ITERATE 跳/ROLLBACK/升级建议；**不得 KEEP** |
| A | 40（+20 iter2） | 4（+2） | v4.5b / final2（+iter2） | `v5-ab-results.md` §A | KEEP / ITERATE / ROLLBACK / INCONCLUSIVE（正式） |
| B | 160–200（封顶 250） | 16–20 | A 档 KEEP 包，整档不换 | `v5-ab-results.md` §B | 达 1300 / 未达 + 后续建议 |

## 6. 待办登记（credits 到位时）

- [ ] A-mini：slot1 A(v4.5b)→0707；slot2 B(final2)→0707；跑完填 §A-mini。
- [ ] 若 INCONCLUSIVE → A 档补 3 场；若 ITERATE → iter2 ×2；若 ROLLBACK → §4 回退。
- [ ] A 档通过（KEEP）→ B 档 16–20 场，每 4 场 checkpoint。
- [ ] 所有场次记录 package_sha 与 uuid；结论发 Lead（一行）+ T1（可执行指令）。

---
预注册时间：credits=0 期间（2026-11-24，round 3 离线准备）。判据一经开跑不得修改；如需改判据，另开新文档编号并在 Lead 批准后废弃本文件。
