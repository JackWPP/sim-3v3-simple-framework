# 上线提交清单（Booster Champion 3v3 第二季）

> 适用版本：v1.8（本文件随每轮迭代更新）。
> 说明：本地已完成构建与验证，**上传由队主自行在赛事官网操作**；本文件是照着做即可的步骤清单。
> 赛事主页：<https://booster.feishu.cn/wiki/Bikkw85DNiz4aWkhXmdciFCxnkg>
> 官网：<https://champion.booster.tech>

## 1. 要上传的文件

| 项 | 值 |
|---|---|
| 产物路径 | `build/com.example.lqinternalmatch-1.1.0.agent` |
| 大小 | 830,718 字节（约 0.8 MB） |
| sha256 | `c1f0e4cb2138e46a16d92505769c60bae85c56b1b80cbc8da6028ce31062ad08` |
| agent id / version | `com.example.lqinternalmatch` / `1.1.0` |
| 入口 | `src/main.py:SoccerSimAgent`（`agent.toml`） |

> 校验：上传前可在本机执行 `sha256sum build/*.agent`，确认与上表一致；
> 每次重新构建后本表会更新（以 `docs/kb/iterations.md` 对应轮次记录为准）。

## 2. 重新构建（改了代码之后）

方式 A（推荐，官方 GUI）：Booster Studio 打开本工程 → 右上角 **Build Agent Only**（锤子图标）
→ 等 `Agent Dev` 输出面板出现 `Built ... successfully` → `build/` 下生成新 `.agent`。

方式 B（命令行，走已注入的 DevTools 桥）：

```bash
cd /home/xgx/wpp1/sim-3v3-simple-framework
python3 tools/bcmd.py --wait 300 booster.agent.build \
  '{"workspacePath":"/home/xgx/wpp1/sim-3v3-simple-framework"}'
```

构建后务必更新本文件的「大小 / sha256」（`ls -la build/ && sha256sum build/*.agent`）。

## 3. 官网提交步骤

1. 浏览器打开 <https://champion.booster.tech>，用统一身份认证（SSO）登录。
2. 进入 **我的队伍**（确认已报名 Booster Champion 3v3 第二季；单人参赛也需先报名建队）。
3. 点 **提交代码**。
4. 首次提交需完成 **5 道规则核验题**（见第 4 节答案要点）；全部答对后提交入口解锁。
5. 上传第 1 节的 `.agent` 文件 → 页面提示 **上传成功** 即完成。
6. 之后到 **我的队伍 → 历史挑战** 查看系统自动对局的比分 / 数据 / 回放。
7. 代码在**比赛中锁定**，比赛结束后可继续提交新版本覆盖；资格赛截止前不限次提交
   （赛事日程：报名 2026-11-16 起，代码提交截止 2026-11-28）。

## 4. 规则核验题答案要点（按官方规则 + 判罚解读）

> 题目文本以官网为准；下面按「官方规则条目 → 正确判据」整理，答错时回查对应条目。

1. **开球/间接任意球进球是否有效**：开球方进球必须满足「≥2 台机器人触球（含对方）」或
   「关键触球点距开球位置 >0.5m」；专属时间过期进入 ball_free 后仍需满足（我方按最严解读执行）。
   单机从开球点直接射门 = 无效球（改判对方球门球）。
   - 规则依据：G-03 / 附录 C《规则与判罚解读》
2. **角球能否直接射门得分**：可以。角球属于「不需要二次触球」的定位球（directFreeKick 同理）。
3. **定位球乌龙**：界外球/球门球/角球第一脚若在触球次数 ≤1 时踢进己方球门 → 进球无效，
   改判对方角球（G-04）。
4. **防守方避让距离**：对方定位球（除开球外）主罚触球瞬间，防守方机器人距球必须 **>1.45m**，
   否则罚下 30s 并重踢；豁免只有两种：站本方门线上（门宽内）或 500ms 内径向远离球速 ≥0.05m/s（R-07）。
5. **抢先触球**：对方定位球主罚触球前，防守方先触球 → 罚下 30s + 重踢（R-06）。
6. **Set/开球站位**：SET 阶段双方全员静止；开球方在本方半场或中圈内，非开球方必须在本方半场
   且离中心 >1.55m（P-01/P-02，判罚 30s）。
7. **罚时与纪律**：罚时 30s，可累加 15s；2 warning → 1 caution，2 caution → 红牌（sentOff）；
   普通罚下 30s 内不得返场，提前返场会被 reset 罚时 + 1 warning。
8. **无活动/倒地**：球距 3m 内 10s 几乎不动 → incapableRobot 罚下；倒地 upDot≤0.45 持续 10s → 罚下。
9. **技术合规**：策略只能使用 `context` 提供的官方信息；禁止 socket/HTTP/文件/proc/端口扫描、
   禁止修改 `src/framework/`、禁止连接 GameControl 等非公开接口。违规可取消资格或判负。

## 5. 上传后自检

- [ ] 页面显示「上传成功」，文件版本/大小与第 1 节一致。
- [ ] 「历史挑战」出现新对局，截图/记录比分（本地同版本战绩见 `iterations.md`）。
- [ ] 若比赛结果与本地差距很大，先确认上传的 `.agent` 是**最新构建**（时间戳/sha256）。
- [ ] 记录一场线上比分到 `docs/kb/iterations.md` 的「线上」小节（便于后续对比）。

## 6. 常见问题

| 现象 | 排查 |
|---|---|
| 「提交代码」按钮灰 / 不可点 | 未完成 5 道规则核验题；或未报名/未建队 |
| 上传失败 | 换浏览器重试；确认文件是 `*.agent` 且大小约 0.8MB；重新登录 SSO |
| 上传成功但对局不动/秒输 | 上传了旧构建；回到第 2 节重新 Build 并核对 sha256 |
| 构建失败 | 检查 `agent.toml` 入口、`build.toml` 依赖；Studio 输出面板看报错；本地先跑 `python3 -m py_compile src/*.py` + `tools/check_names.py` |
| 想区分版本 | 可自行 bump `agent.toml` 的 `version` 后重新构建；官方以文件内容为准 |
| 需要旁观对局 | 官网「我的队伍 → 历史挑战」有比分/数据/回放 |

## 7. 合规检查表（提交前）

- [ ] `src/framework/` 未改动；入口签名 `SoccerSimAgent(SoccerAgentMixin, AgentBase)`、`play/init_store` 未变。
- [ ] 无新增第三方依赖；`build.toml` 仅 `py_trees==2.4.0`。
- [ ] 策略代码无网络/文件 IO/子进程；所有信息来自 `context`。
- [ ] `python3 -m py_compile src/main.py src/player.py src/param.py` 通过、`tools/check_names.py` 输出 `CHECK_OK`。
- [ ] 本地至少跑过一整场（`tools/matchrun.py`），`docs/kb/logs/<tag>-summary.txt` 里我方罚单/比分可查。
