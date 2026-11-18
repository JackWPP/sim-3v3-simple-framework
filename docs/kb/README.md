# 3v3 仿真足球策略知识库

本目录是「Booster Champion 3v3 仿真机器人足球赛」策略工程的资料与实验记录。
入口文件按用途分四类：

## 1. 规则原文与解读

| 文件 | 内容 |
|---|---|
| `official-rules.md` | 官方《锦标赛比赛规则》全文（飞书 doc token `OK0ywG6DcimdiNkTbk9cmCPenne`，5513 字） |
| `rules-interpretation.md` | 官方《规则与判罚解读》附表 C（doc token `StwWwwDXziUx9JkekwecsqmPn4f`，6204 字） |
| `referee-mechanics.md` | 从仿真器自动裁判源码（`/tmp/gc/game_control`）逆向核实的判定实现：阈值、状态机、触球计数、出界/重启位置、准备阶段闸门 |
| `course/` | 官方「仿真足球赛专题课」13 讲摘要（见 `course/README` 说明或各文件头部） |

关键结论摘要：

- 我方 = team_id **1** = `home` = `robot1/robot2/robot3`；对手 Booster AI = `team2` = `away`。
- 比赛 10 分钟（仿真时间）；无上下半场。
- 开球/界外球/球门球/间接任意球：开球方进球须「≥2 台机器人触球」或「触球点距开球点 >0.5m」。
  角球、直接任意球不受此限（可直接射门）。
- 对方定位球（除开球）脱离房间前：所有防守方距球 >1.45m（判定线），主罚触球瞬间判罚。
- READY 阶段双方全员静止 5s 才进 SET（仿真里 SET 固定 5s 后进 PLAYING）。
- 每个解除罚：30s + 15s × 计数（illegalPositioning/motionInSet 等不计入计数）。
- 球门球摆球点 `(±6.0, ±2.0)`，角球 `(±6.95, ±4.45)`，界外球 `(clamp(ball.x, ±6.95), ±4.45)`。

## 2. 迭代记录

阶段总结报告见 `final-report.md`（任务完成情况、战绩表、主要修复、下一步）。

`iterations.md`：每一轮「改了什么 → 跑出什么比分/罚单/触球 → 为什么」的完整实验记录，
以及**部署校验协议**（py_compile → `tools/check_names.py` → 部署后查 agent 日志
`tick failed=0`/`teammates_seen=3/3`）。

对局原始存档在 `logs/`：`baseline-01.json`、`iteration-02.json` … `iteration-12.json`
（每次 matchrun 自动保存 status + 全部裁判事件），`*-runner/` 是赛后拷出的容器运行日志。

## 3. 工具链

| 工具 | 用途 |
|---|---|
| `tools/matchrun.py` | 一键：build → stop → run → 校验 → start3v3Match → 监视 → 存档 → docker cp runner 日志 → 分析 |
| `tools/matchw.py` | 只监视并保存 status+logs（可比赛中途开始） |
| `tools/analyze_match.py` | 把存档 JSON 汇总成：比分、进球时间线、罚单明细（含 measurements）、触球数 |
| `tools/check_names.py` | 静态 AST 检查：`src/*.py` 里引用的全大写常量是否都在 `src/param.py` 定义（防部署后 NameError） |
| `tools/bcmd.py` | 经 Studio DevTools 桥（127.0.0.1:8765）向 Studio 主进程发命令（build/run/start/end/get3v3MatchLogs 等） |
| `tools/xgui.py` | 纯 ctypes X11 键鼠/截图（DISPLAY=:99），Studio 菜单与 DevTools 操作 |

## 4. 策略代码

| 文件 | 作用 |
|---|---|
| `src/main.py` | 阶段状态机 `get_phase`、`play()` 分派、`_act_*` 各阶段行为 |
| `src/player.py` | 单机器人技能：`kick`/`attack`/`guard`/`support`/`walk_to`/`omni_move_toward`/`take_kickoff` |
| `src/param.py` | 全部可调参数（踢球力度、速度、安全距离、门将参数等） |

当前策略版本 **v1.7**：v1.1 合规重写（定位球四类、避让撤离、STOPPED 闸门、READY 槽位锁定）
→ v1.5 门将门线横移 + hold_line 退到球后 2.2m → v1.6 球出界后主动后退 → v1.7 我方开球
非主罚球员退回本方半场/圈外。近期有效战绩：3:2 胜、5:3 胜、3:2 胜（0 罚单）、1:3 负。
详见 `iterations.md` 指标表与每轮分析。

## 5. 复现一次对局

```bash
# 前提：Studio 已打开工程、DevTools 已注入桥（见 iterations.md/桥恢复步骤）
cd /home/xgx/wpp1/sim-3v3-simple-framework
python3 -m py_compile src/player.py src/main.py src/param.py
python3 tools/check_names.py
python3 -u tools/matchrun.py --tag iteration-NN --max-wait 1200
python3 tools/analyze_match.py docs/kb/logs/iteration-NN.json
```
