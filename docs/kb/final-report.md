# Booster Champion 3v3 仿真足球 — 策略工程阶段报告

日期：2026-11-18　项目：`/home/xgx/wpp1/sim-3v3-simple-framework`

## 一、任务与完成情况

用户目标（三件事）与状态：

1. **研读全部赛事文档** — 完成。
   - 官方《锦标赛比赛规则》全文（`docs/kb/official-rules.md`）
   - 官方《规则与判罚解读》附表 C（`docs/kb/rules-interpretation.md`）
   - 「仿真足球赛专题课」13 讲摘要（`docs/kb/course/`）
   - 官方 FAQ / 报名与提交指南要点（`docs/kb/course/08-appendix-a-faq.md` 等）
   - **额外**：从仿真器自动裁判源码逆向核实判定细节（`docs/kb/referee-mechanics.md`），
     比文档更精确（阈值、状态机、触球计数、出界/重启位置、准备阶段闸门）。
2. **利用文档知识模拟与优化策略、击败对手** — 已形成闭环并取得胜绩。
   - 打通「改代码 → 构建 → 部署 → 开赛 → 监视 → 存档 → 分析」全自动链路；
   - 有效对局战绩：baseline 1:6 负 → 2:2 平 → 2:3 负 → 2:5 负 → **3:2 胜 → 5:3 胜 → 3:2 胜 → 1:3 负**；
   - 最近一局 0 罚单（v1.7），合规修复生效。
3. **建立自迭代机制** — 完成并沉淀为仓库内工具/文档（见下）。
   - `tools/matchrun.py` 一键闭环；`tools/check_names.py` 静态检查防 NameError；
   - `docs/kb/iterations.md` 记录每轮改动、比分、罚单、根因、部署校验协议；
   - `docs/kb/README.md` 作为知识库入口。

## 二、关键规则结论（经裁判源码核实）

- 我方 = team_id **1** = `home` = robot1/2/3；对手 Booster AI = `team2` = `away`。
- 比赛 10 分钟仿真时间，无上下半场；金球加时 5 分钟/轮（淘汰赛）。
- 开球/界外球/球门球/间接任意球：开球方进球须「≥2 台机器人触球」或「触球点距开球点 >0.5m」；
  角球、直接任意球不受此限（可直接射门）。
- 自由球避让：对方定位球（不含开球）主罚触球瞬间，防守方距球须 >1.45m（判定线），
  否则 30s + 重踢。豁免：站本方门线且 |y|≤1.35，或 500ms 内径向远离速度 ≥0.05m/s。
- 开球站位：踢球方须在本方半场或中圈内；非踢球方须在本方半场且离中心 >1.55m。
- READY 阶段双方全员静止 5s 才进 SET；SET 固定 5s 后进 PLAYING。
- 罚时：30s + 15s × 计数（illegalPositioning/motionInSet 等不计入计数递增）。
- 球门球摆球点 (±6.0, ±2.0)，角球 (±6.95, ±4.45)，界外球 (clamp(ball.x, ±6.95), ±4.45)。
- 球出界后摆球点就在出界点附近 → 「贴着出界点追球」必然吃到干扰/避让罚单（重要教训）。

## 三、自动化对局闭环

Studio 未开放 MCP 给本会话，最终通过 **DevTools 桥**实现外部控制：

```
Studio（Electron 页面）
  └─ window.boosterCommands.executeCommand(...)   # 主进程命令
       ↑ HTTP 轮询（fetch）
/tmp/booster_bridge.py  127.0.0.1:8765            # 长轮询队列
       ↑
tools/bcmd.py / tools/matchrun.py                 # CLI 下发命令
```

可执行命令：`booster.agent.build / run / stop / getRecentLogs / getProjectInfo`、
`booster.agent.start3v3Match / end3v3Match / get3v3MatchStatus / get3v3MatchLogs`。

复现一局：

```bash
cd /home/xgx/wpp1/sim-3v3-simple-framework
python3 -m py_compile src/player.py src/main.py src/param.py
python3 tools/check_names.py
python3 -u tools/matchrun.py --tag iteration-NN --max-wait 1200
python3 tools/analyze_match.py docs/kb/logs/iteration-NN.json
```

产物：`docs/kb/logs/iteration-NN.json`（status + 全部裁判事件）、`iteration-NN-runner/`
（容器内 agent 日志）、`iteration-NN-summary.txt`（分析摘要）。

## 四、迭代战绩

| 轮次 | 版本 | 比分 | 我方罚单 | 对方罚单 | 触球 | 事件 | 时长(s) |
|---|---|---|---|---|---|---|---|
| baseline-01 | v1.0 示例 | 1:6 负 | 3 | 0 | 25:25 | 149 | 668 |
| iteration-02 | v1.1 合规重写 | 2:2 平 | 4 | 1 | 44:44 | 283 | 700 |
| iteration-04 | v1.3 | 2:3 负 | **0** | 1 | 40:39 | 189 | 661 |
| iteration-08 | v1.4b | 2:5 负 | 3 | 1 | 18:17 | 149 | 683 |
| iteration-09 | v1.5 | **3:2 胜** | 2 | 2 | 38:38 | 299 | 715 |
| iteration-10 | v1.6 | **5:3 胜** | 4 | 0 | 30:30 | 193 | 701 |
| iteration-11 | v1.6 重跑 | **3:2 胜** | **0** | 1 | 30:30 | 205 | 672 |
| iteration-12 | v1.7 | 1:3 负 | 1 | 0 | 45:45 | 224 | 662 |

无效局（冻结/崩溃，已剔除）：iteration-03（M-02 提前停）、05（NameError 崩溃）、
06（stale run 导致 context 全空）、07（同崩溃）。

## 五、主要合规修复（对应官方规则 / 裁判源码）

1. `_act_opp_set_play` 不再转 `_act_normal` 抢球：门将回小禁区，其余人退到「球→己方门 3.3m」
   等待点（>1.45m 判定线、>3m 避开 M-05）；离球 <2.7m 用 `omni_move_toward` 全向平移撤离。
2. STOPPED 阶段：`_act_stopped` 全员静止；仅裁判 1.5s 宽限期内允许撤离（`STOP_GRACE_MOVE_S=0.7`，
   实测 1.2s 会因发布延迟被判 M-02）。
3. 我方定位球四类分别实现（角球传中/射门、直接任意球射门、界外球/球门球向前场踢、
   摆球 stopped 时全员静止），避免乌龙与二次触球规则违规。
4. 开球：我方踢 +x 方向；非主罚球员退回本方半场/圈外（v1.7），对方开球等待点 3.2m。
5. READY 槽位锁定（`store.ready_assignment`），避免逐帧重排导致永远凑不满静止 5s。
6. 球出界后主动后退到出界点内侧 ~2.4m（v1.6），消除摆球点脚下干扰罚单。
7. 门将门线横移封角度（`cover_y=clamp(ball.y*0.65,±1.05)`），并保留 M-05 防呆微移。
8. `attack` 的 hold_line 只在对方重启窗口生效（球贴对方底线时退到球后 2.2m），避免活球僵局。

## 六、剩余问题与下一轮（v1.8）建议

1. **倒地被罚下**（fallenRobot）：3 局出现 3 次（10s 内 BoosterOS 未自动起身），
   策略只能减少贴身缠斗、保证 `ensure_ready()` 每帧调用，属系统恢复能力边界。
2. **进攻转化率**：触球 45:45 但射门转化 1:3（iteration-12），定位球第一脚力度偏大易出界
   （全场 13 次界外球/球门球），建议 FORWARD 8.0→6.0 并瞄准场内更安全落点。
3. **开球被反击**：iteration-12 末段开球后丢球，建议开球改回传/横传。
4. 减少三台同时压上抢球（被撞倒 + 乱战丢球）。

## 七、仓库改动

- 策略：`src/main.py`（+466 行，六类阶段行为重写）、`src/player.py`（+110 行）、`src/param.py`（+40 行）
- 工具：`tools/{matchrun,matchw,analyze_match,check_names,bcmd,xgui}.py`
- 文档：`docs/kb/{official-rules,rules-interpretation,referee-mechanics,iterations,README,final-report}.md`、
  `docs/kb/course/`（13 篇摘要）、`docs/kb/logs/`（对局存档）
