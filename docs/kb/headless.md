# Headless 3v3 仿真（脱离 Studio UI 的快速迭代环境）

> 目标：不启动 Booster Studio 的 3D 渲染/相机管线，直接在 docker 内跑完整 3v3 比赛，
> 把「改代码 → 构建 → 跑一场 → 拿结果」的迭代周期压到最短。
> 当前状态：**已跑通完整比赛并用于策略迭代**（v1.9→v1.14 共 6 场：
> headless-03 4:0 胜、headless-08 3:2 胜且 0 罚单 0 僵局 0 无效进球，单场墙钟 ~480-500s ≈1.25x）。
> 已知遗留问题见文末「已知问题」。

## 1. 为什么更快

| 项 | Studio 模式 | headless 模式 |
|---|---|---|
| 3D 渲染 / 相机扩展 | 宿主机 Electron + camera renderer + 容器内 bs-ext-depth/rgb/detect（约 1.5-2 核） | 全部关闭（`--no-camera-relay`，不连渲染） |
| 仿真速度 | target=1.0 时实际 0.7–0.99x（受渲染争用） | target=1.0 时实际 0.97–0.99x |
| 运行期调速 | 可（ws://127.0.0.1:8788 `set_speed`），但受渲染争用，实际 1.6–2.2x | 可，物理-only 上限约 2.7x（≈1300 steps/s） |
| 启动依赖 | Studio 进程 + extension host + DevTools 桥 | 只需 docker 容器（无 GUI） |
| 单场墙钟 | 约 690–850s | 612s（1x）；2x 预计 ~350s |

物理参数：K1 3v3 场景 MuJoCo dt≈2ms；1x 实时≈486 physics steps/s；物理-only 容器
`step_us_p50≈500µs`，`steps=15026` 时 `step_overrun=0`。

## 2. 目录 / 容器布局

实验目录 `/tmp/headless`（宿主机）：

```
/tmp/headless/
  simsrc/    # robocup_sim_src 副本 + 从镜像拷出的 .venv(405MB)
  library/   # ~/.config/"Booster Studio"/simulator-library 副本(281MB)
  runner/    # football3v3_runner 副本（run.py/supervisor.py/...）
  agent_data/# 容器内 /opt/booster/booster_agent_data 的持久化目录
  scripts/   # launch_sim.sh / probe_speed.py
```

容器 `sim-lab`（长期保留，`--privileged`、`--shm-size=256m`，无端口映射）：

```
docker run -d --name sim-lab --privileged --shm-size=256m \
  -v /tmp/headless/simsrc:/usr/local/booster_robot/booster_robocup_sim \
  -v /tmp/headless/library:/opt/booster-studio/library \
  -v /tmp/headless/agent_data:/opt/booster/booster_agent_data \
  -v /tmp/headless/runner:/match -v /tmp/headless/scripts:/scripts:ro \
  -v <repo>/build:/agents:ro \
  -v /usr/share/booster-studio/resources/app/booster-native/statics/ai-agent:/agents-ai:ro \
  -e BOOSTER_SIM_LIBRARY_ROOT=/opt/booster-studio/library \
  -e BOOSTER_EMBEDDED_MOTION=1 -e ROS_DOMAIN_ID=0 \
  -e FASTRTPS_DEFAULT_PROFILES_FILE=/opt/booster/BoosterRos2/fastdds_profile.xml \
  boiler-robotics-registry.cn-beijing.cr.aliyuncs.com/virtual-robot/virtual-robot:0.9.10-alpha-humble \
  bash -lc 'sleep infinity'
```

启动仿真（容器内）：`/scripts/launch_sim.sh`（= source ROS → `app_in_container.py
--scene-key football_match_pitch_6_K1 --no-camera-relay`）。启动后容器内监听
8788（物理 WS）、38383（GameControl HTTP）；`GET /health` 返回 ready 即可。

> 注：镜像名必须带完整 registry 前缀（本地无 `virtual-robot:0.9.10-alpha-humble` tag，
> 直接 docker run 会去 docker.io 拉取失败）。

## 3. 一键跑一场

```bash
python3 tools/headless_match.py --tag headless-02            # 1x
python3 tools/headless_match.py --tag headless-03 --speed 2.0  # 2x 提速
```

内部流程（详见 `tools/headless_match.py`）：

1. `ensure_container()`：复用/创建 `sim-lab`；
2. `ensure_sim()`：`/health` 未 ready 就后台 `launch_sim.sh` 并等待；
3. `install_agents()`：把 `build/*.agent`（最新）与官方 BoosterAI 包
   `com.booster.default3v3ai.agent` 安装到 `.../agents/extract`；
4. `run.py --teams com.example.lqinternalmatch com.booster.default3v3ai`，
   等 `all 3v3 agents are active`（≈95s，见下）；
5. `POST /match/start`；可选 `set_speed(<factor>)`（ws 8788）；
6. `tools/headless_monitor.py` 轮询 `/status`（10s）直到 `isFinal`，archived 时把
   `/status`、`/result`、`/events/history?limit=5000` 以标准 schema 写入
   `docs/kb/logs/<tag>.json`；`docker cp /run/3v3_runner` 存为 `<tag>-runner/`；
7. `tools/analyze_match.py` 输出报告。

产物：`docs/kb/logs/<tag>.json`、`<tag>-runner/`（含 team_1/team_2 agent 日志）、
`<tag>-summary.txt`。

## 3.5 离线构建 .agent（不依赖 Studio GUI）

headless 迭代不需要 Studio 的 Build Agent Only，可直接在 agent-dev 镜像里构建：

```bash
docker run --rm --entrypoint bash   -e AGENT_SIGN_KEYSTORE=/.agent_dev/keystore.p12 \
  -e AGENT_SIGN_KEYSTORE_PASSWD=123456 \
  -v "$PWD":/workspace/src/b4dda6cfc949d2cf921c81c2b976183d \
  booster-robotics-registry.cn-beijing.cr.aliyuncs.com/agent-dev/agent-dev:0.9.17-alpha-humble \
  -lc 'cd /workspace/src/b4dda6cfc949d2cf921c81c2b976183d && /sdk/agent_bundler/build_pyagent .'
```

要点：
- 镜像 entrypoint 是 `exec "$@"`，必须 `--entrypoint bash` 才能用 `-lc`；
- 镜像内自带签名 keystore：`/.agent_dev/keystore.p12`（密码 123456，Studio 只用同一份）；
  省略 `[sign]` 时 builder 从环境变量 `AGENT_SIGN_KEYSTORE` / `AGENT_SIGN_KEYSTORE_PASSWD` 读取；
- 产物写到 `build/<id>-<version>.agent`，随后 `tools/headless_match.py` 会自动安装最新的；
- 完整「改代码 → 构建 → headless 跑一场 → 分析」示例：

```bash
python3 -m py_compile src/main.py src/player.py src/param.py && python3 tools/check_names.py
docker run --rm --entrypoint bash -e AGENT_SIGN_KEYSTORE=/.agent_dev/keystore.p12 \
  -e AGENT_SIGN_KEYSTORE_PASSWD=123456 -v "$PWD":/workspace/src/b4dda6cfc949d2cf921c81c2b976183d \
  <agent-dev-image> -lc 'cd /workspace/src/b4dda6cfc949d2cf921c81c2b976183d && /sdk/agent_bundler/build_pyagent .'
python3 -u tools/headless_match.py --tag headless-03 --timeout 900
```

## 4. 关键坑与修复

1. **agent 激活超时（最重要）**：headless 中 agent 从启动到 Active 约 **95s**（Studio 里 2.3s）。
   原因是 Booster OS 初始化要等 `booster-cli robot_info`（10s 超时）、camera API（5s 失败回退）、
   音频/手柄等逐一失败回退；framework node 的 `/booster_rpc_service` 等这些完成才就绪。
   `run.py` 默认 `wait_for_agents_ready(timeout=45.0)` 太短 → 报
   `timed out waiting for agent lifecycle activation: team_1`。
   **修复**：把 `/tmp/headless/runner/run.py` 的默认超时改成 180s
   （`def wait_for_agents_ready(timeout: float = 180.0, ...)`）。重建 lab 时需要重打。
2. **docker run 的 -lc 传参**：镜像 entrypoint 是 `/ros_entrypoint.sh` + `exec "$@"`，
   想用 `bash -lc` 必须显式 `--entrypoint /bin/bash`，否则报
   `No such file or directory`。
3. **rclpy / ROS 环境**：容器 `.venv` 用 `uv venv --system-site-packages` 创建，
   必须 source `/opt/ros/humble/setup.bash` 与 `/opt/booster/BoosterRos2/install/setup.bash`
   后再用 `.venv/bin/python`，否则 game_control 扩展报 `No module named 'rclpy'`。
4. **run.py 的 sandbox**：需要 `--privileged`（unshare/mount/nsenter + cgroup v2）。
5. **switches**：`--no-camera-relay` 关闭相机 hub（9876）；不连渲染时 bs-ext 相机会
   反复重试，属正常噪声。不要用 `--no-extension-process`，GameControl 扩展需要它。
6. **GameControl HTTP**：端口在容器内 38383；容器没有映射到宿主，统一通过
   `docker exec ... curl` 调用。`/events/history` 默认 limit=50，必须显式
   `?limit=5000` 才能取全量。

## 5. 实验结果

| tag | 比分（我方=home） | 墙钟 | 有效速度 | 备注 |
|---|---|---|---|---|
| headless-01 | **2 : 1 胜** | 612s（sim 600s） | ≈0.98x | 无 set_speed；后段出现冻结（见已知问题） |
| headless-02 | **2 : 1 胜** | 500s（sim 600s） | ≈1.2x | 开赛约 40s 后 set_speed(2.0)（比赛中途生效）；全程触球到 575s，仅 1 次 game_stuck |
| headless-03 | **4 : 0 胜** | 481.8s | ≈1.25x | v1.9；我方 2 罚（出界后贴球）、对方 4 罚；touch 51；1 次无效进球 |
| headless-04 | 1 : 1 平 | 391.3s | ≈1.25x | v1.10；line_hold 过度保守：2 次 game_stuck、3 次 goal_disallowed_indirect |
| headless-05 | 0 : 2 负 | 451.4s | ≈1.25x | v1.11；line_clear 目标点被 clamp 回场内→4 次 game_stuck、touch 仅 25 |
| headless-06 | 2 : 4 负 | 471.7s | ≈1.25x | v1.12；stuck 归零、touch 46；1 次 opening 直接射门无效（G-05） |
| headless-07 | 0 : 1 负 | 481.5s | ≈1.25x | v1.13；开球改短传后 0 次无效进球；1 罚（对方快发界外球贴太近）、2 次 stuck |
| headless-08 | **3 : 2 胜** | 481.5s | ≈1.25x | v1.14；**0 罚单、0 stuck、0 无效进球、touch 73**（当前最佳） |

- 对比 Studio（v1.8b, 1x target）：4:2 胜 / 692s ≈0.87x；headless 无 3D 渲染时可达 0.98x，
  开 set_speed 后可到 ~1.2-1.5x（受 agent 进程与扩展 CPU 限制，未达物理-only 的 2.7x）。
- 两场 headless 都 2:1 胜 BoosterAI，与 Studio 结论方向一致，可用于快速验证。

## 6. 已知问题（待解决）

- **headless 结果波动大**：同一版本不同局比分可从 0:2 到 4:0（BoosterAI 行为受随机性影响）；
  战术有效性仍以多场统计 + Studio 1x 为准，headless 主要用于淘汰明显违规/僵局/崩溃。
- **headless-01 后段冻结（未复现）**：soccer 时钟 ~326s 后全场再无 ball_touch；
  怀疑与 embedded motion/球接触有关；headless-02 之后再未出现，暂按随机异常处理。
- **激活固定开销 ~95-105s**：就绪等待超时必须 ≥180s；可考虑预启动 sandbox 进一步压缩。
- `robot_info.txt`、`/opt/booster/bin` 服务栈在 headless 容器中缺失（Studio 启动时注入）；
  目前不影响激活与比赛。
- **Studio 部署通道当前不可用**：DevTools 注入的 BOOT_JS 超时仍是 20s（需要重载窗口重新注入
  240s 版本），`bcmd stop/run` 会返回 timeout；Studio 1x 复验暂时只能用旧版（iteration-15 的
  v1.8b 4:2）。恢复步骤：重载 Studio 窗口 → 帮助→切换开发人员工具 → 注入 boot.js。

## 6. 参考：与 Studio 的等价关系

- Studio 本地 3v3 比赛 = 起容器(app_in_container + GameControl extension)
  → `run.py --teams A B` → 等 ready → `POST /match/start` → 结束后
  `/result` + `/events/history`；本方案把「起容器 + ready + start」全部脚本化。
- 裁判/规则完全一致（同一 `extensions/game_control` 代码）；球/机器人物理一致。
