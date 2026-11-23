#!/usr/bin/env python3
"""replay_playcheck.py —— 离线回放自检：逐帧重建 Context 调策略 play()，抓异常/冻结。

背景
----
第 4 场线上对局（f751146f, v2.8）7 张 inactiveRobot 的根因是 ``_act_normal`` 的
presser 分支裸引用了未定义的局部变量 ``ball``：只要「球速 < 0.2 m/s + PLAYING +
开放球权」就每帧抛 ``NameError``，框架 ``runtime._loop`` 捕获异常后对**全员**
``p.stop()`` → 全队冻结，球一停就长时间没人动，直到对手把球踢动才恢复。
第 3 场（v2.7）同一 bug，第 5 场（v2.9）同一 bug。线上比赛里这类异常不会中断比赛，
只会让回放看起来「我方三台同时无 move/kick 指令」，人工很难发现。

本工具把「策略在整场回放里 0 异常」变成可复跑的提交门禁：用归档回放
(``docs/kb/online-matches/<uuid>-manifest.json`` + ``<uuid>-segments/``) 逐帧重建
平台 Context（队友/对手位姿、球、裁判状态、罚下窗口），直接调用当前 ``src/`` 的
``SoccerSimAgent.play()``，统计异常、打印首个 traceback，并把异常帧与
replay ``commandIntents`` 里「我方三台同时无 move/kick」的冻结窗口做对照。

用法
----
    python3 tools/replay_playcheck.py <uuid> [<uuid> ...]
    python3 tools/replay_playcheck.py <uuid> --git-ref 5f60659     # 检查历史版本
    python3 tools/replay_playcheck.py <uuid> --src src             # 默认
    python3 tools/replay_playcheck.py <uuid> --json out.json       # 机器可读结果

退出码：0 = 全部回放 0 异常（门禁通过）；1 = 存在异常（门禁失败）；2 = 参数/数据错误。

说明
----
* 平台 SDK（``booster_agent_framework`` / ``boosteros``）用内存桩替代，开发机无需安装。
* 裁判状态由 manifest ``events[].game`` 快照重建；开球期 ``secondaryTime`` 线性衰减；
  球越过底线/边线（超出 0.135 m 容差）时按 ``stopped=True`` 处理。
* 本工具只读回放与策略源码，不修改仓库、不联网。
"""

from __future__ import annotations

import argparse
import dataclasses
import gzip
import importlib
import json
import math
import os
import subprocess
import sys
import tarfile
import tempfile
import traceback
import types
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_MATCHES_DIR = REPO_ROOT / "docs" / "kb" / "online-matches"

# 场地与出界阈值（与 src/framework/types.py ADULT_FIELD_DIMENSIONS / 裁判一致）
FIELD_LENGTH = 14.0
FIELD_WIDTH = 9.0
OUT_MARGIN = 0.135  # |x| - OUT_MARGIN > length/2 判出界；这里统一用半场/半宽

STATE_MAP = {
    "initial": "INITIAL",
    "ready": "READY",
    "set": "SET",
    "playing": "PLAYING",
    "finished": "FINISHED",
}
# replay 的 setPlay 是展示语义（camelCase）：kickOff 对应框架 SetPlay.NONE + 开球窗口
SETPLAY_MAP = {
    "noSetPlay": "NONE",
    "kickOff": "NONE",
    "throwIn": "THROW_IN",
    "goalKick": "GOAL_KICK",
    "cornerKick": "CORNER_KICK",
    "directFreeKick": "DIRECT_FREE_KICK",
    "indirectFreeKick": "INDIRECT_FREE_KICK",
    "penaltyKick": "PENALTY_KICK",
}
KICK_SIDE_MAP = {"home": 1, "away": 2}


# ----------------------------------------------------------------------
# 回放加载
# ----------------------------------------------------------------------


def load_manifest(uuid: str, matches_dir: Path) -> dict:
    path = matches_dir / f"{uuid}-manifest.json"
    if not path.exists():
        raise SystemExit(f"[replay_playcheck] 找不到 manifest: {path}")
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def load_frames(uuid: str, manifest: dict, matches_dir: Path) -> list[dict]:
    seg_dir = matches_dir / f"{uuid}-segments"
    if not seg_dir.is_dir():
        raise SystemExit(f"[replay_playcheck] 找不到 segments 目录: {seg_dir}")
    frames: list[dict] = []
    bad_lines = 0
    for seg in manifest.get("segments", []):
        path = seg_dir / seg["path"]
        if not path.exists():
            raise SystemExit(f"[replay_playcheck] 缺段: {path}")
        with gzip.open(path, "rt", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    frames.append(json.loads(line))
                except json.JSONDecodeError:
                    bad_lines += 1  # 服务端偶发半帧残尾，跳过
    frames.sort(key=lambda f: f.get("time", 0.0))
    if bad_lines:
        print(f"[replay_playcheck] 跳过损坏帧行 {bad_lines} 条")
    return frames


# ----------------------------------------------------------------------
# 裁判状态重建
# ----------------------------------------------------------------------


class GameRecon:
    """由 manifest events 重建每帧 game 快照（state / setPlay / stopped / 罚下窗口）。"""

    def __init__(self, manifest: dict):
        snaps = []
        penalties: dict[tuple[str, int], list[list[float]]] = {}
        for ev in manifest.get("events", []):
            t = ev.get("simTime")
            game = ev.get("game")
            if t is None:
                continue
            if game:
                snaps.append((float(t), game))
            etype = ev.get("type")
            actor = ev.get("actor") or {}
            side = actor.get("side")
            pno = actor.get("playerNumber")
            if side in ("home", "away") and isinstance(pno, int):
                key = (side, pno)
                if etype == "penalty":
                    secs = 30.0
                    out = ev.get("outcome") or {}
                    if isinstance(out.get("seconds"), (int, float)):
                        secs = float(out["seconds"])
                    penalties.setdefault(key, []).append([float(t), float(t) + secs])
                elif etype == "penalty_complete":
                    # 用官方结束时刻收紧时长
                    for win in reversed(penalties.get(key, [])):
                        if win[0] <= float(t) <= win[1] + 120.0 and win[1] > float(t):
                            win[1] = float(t)
                            break
        snaps.sort(key=lambda item: item[0])
        self.snaps = snaps
        self.penalties = penalties

    def snapshot(self, t: float) -> dict | None:
        lo, hi = 0, len(self.snaps)
        while lo < hi:
            mid = (lo + hi) // 2
            if self.snaps[mid][0] <= t:
                lo = mid + 1
            else:
                hi = mid
        if lo == 0:
            return None
        return self.snaps[lo - 1][1]

    def penalty_of(self, side: str, player_number: int, t: float) -> bool:
        for start, end in self.penalties.get((side, player_number), []):
            if start <= t < end:
                return True
        return False

    def state_at(self, t: float, ball: tuple[float, float] | None) -> dict:
        """返回 {state,set_play,stopped,secondary_time,kicking_team}。"""
        snap = self.snapshot(t)
        if snap is None:
            return {
                "state": "INITIAL",
                "set_play": "NONE",
                "stopped": False,
                "secondary_time": 0.0,
                "kicking_team": 255,
            }
        state = STATE_MAP.get(str(snap.get("state", "initial")).lower(), "INITIAL")
        set_play = SETPLAY_MAP.get(str(snap.get("setPlay", "noSetPlay")), "NONE")
        stopped = bool(snap.get("stopped", False))
        kicking = KICK_SIDE_MAP.get(str(snap.get("kickingSide") or "").lower(), 255)
        sec = float(snap.get("secondaryTime") or 0.0)
        # 开球窗口：setPlay 已映射成 NONE、secondaryTime 从 10 递减到 0
        if set_play == "NONE" and sec > 0.0 and state == "PLAYING" and not stopped:
            elapsed = t - self._snap_time(t)
            sec = max(0.0, sec - max(0.0, elapsed))
        # 球已在场外但裁判事件还没到达时，按 stopped 处理（避免误报异常）
        if ball is not None and state == "PLAYING" and not stopped:
            bx, by = ball
            if abs(bx) > FIELD_LENGTH / 2.0 + OUT_MARGIN or abs(by) > FIELD_WIDTH / 2.0 + OUT_MARGIN:
                stopped = True
        return {
            "state": state,
            "set_play": set_play,
            "stopped": stopped,
            "secondary_time": sec,
            "kicking_team": kicking,
        }

    def _snap_time(self, t: float) -> float:
        lo, hi = 0, len(self.snaps)
        while lo < hi:
            mid = (lo + hi) // 2
            if self.snaps[mid][0] <= t:
                lo = mid + 1
            else:
                hi = mid
        return self.snaps[lo - 1][0] if lo else 0.0


# ----------------------------------------------------------------------
# 策略加载（当前 src/ 或 git 历史版本）
# ----------------------------------------------------------------------


class _AgentBaseStub:
    def __init__(self, *args, **kwargs):
        self.logger = None

    def init_store(self, store) -> None:  # pragma: no cover - 由策略覆盖
        pass


def install_sdk_stubs() -> None:
    """在 sys.modules 注入平台 SDK 桩（无需安装 Booster SDK）。"""
    if "booster_agent_framework" not in sys.modules:
        mod = types.ModuleType("booster_agent_framework")

        class AgentBase:  # noqa: D401 - stub
            def __init__(self, *args, **kwargs):
                self.logger = None

            def init_store(self, store) -> None:
                pass

        class AgentFeatures:
            pass

        mod.AgentBase = AgentBase
        mod.AgentFeatures = AgentFeatures
        sys.modules["booster_agent_framework"] = mod

    if "boosteros" not in sys.modules:
        pkg = types.ModuleType("boosteros")
        pkg.__path__ = []  # 包标记
        robots = types.ModuleType("boosteros.robots")
        robots.__path__ = []
        booster = types.ModuleType("boosteros.robots.booster")

        class BoosterRobot:  # noqa: D401 - stub
            pass

        class SoccerKickManager:  # noqa: D401 - stub
            def __init__(self, *args, **kwargs):
                pass

            def start(self, *args, **kwargs):
                pass

            def stop(self, *args, **kwargs):
                pass

            def update_command(self, *args, **kwargs):
                pass

            def update_ball(self, *args, **kwargs):
                pass

        booster.BoosterRobot = BoosterRobot
        booster.SoccerKickManager = SoccerKickManager
        robots.booster = booster
        pkg.robots = robots
        sys.modules["boosteros"] = pkg
        sys.modules["boosteros.robots"] = robots
        sys.modules["boosteros.robots.booster"] = booster


def load_strategy(src_arg: str | None, git_ref: str | None):
    """返回 (src_root, 描述, src.main 模块)。"""
    install_sdk_stubs()
    tmpdir = None
    if git_ref:
        tmpdir = tempfile.mkdtemp(prefix="playcheck_src_")
        proc = subprocess.run(
            ["git", "archive", git_ref, "src"],
            cwd=str(REPO_ROOT),
            capture_output=True,
        )
        if proc.returncode != 0:
            raise SystemExit(
                f"[replay_playcheck] git archive {git_ref} 失败: {proc.stderr.decode(errors='replace')[:300]}"
            )
        archive = os.path.join(tmpdir, "src.tar")
        with open(archive, "wb") as fh:
            fh.write(proc.stdout)
        with tarfile.open(archive) as tar:
            tar.extractall(tmpdir)
        src_parent = Path(tmpdir)
        desc = f"git {git_ref}"
    else:
        src_parent = Path(src_arg or (REPO_ROOT / "src")).resolve().parent
        desc = str(src_parent / "src")
    for name in list(sys.modules):
        if name == "src" or name.startswith("src."):
            del sys.modules[name]
    sys.path.insert(0, str(src_parent))
    try:
        main_mod = importlib.import_module("src.main")
    finally:
        sys.path.pop(0)
    return src_parent, desc, main_mod


# ----------------------------------------------------------------------
# 逐帧执行
# ----------------------------------------------------------------------


class StubBackend:
    """替代 RobotBackend：只记录命令，不连接机器人。"""

    def __init__(self, player_id: int):
        self.player_id = player_id
        self._mode = "walk"
        self._fall_down_state = "normal"
        self._getting_up = False
        self._kicking = False
        self.moves: list[tuple[float, float, float]] = []
        self.kicks: list[tuple[float, float]] = []

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def fall_down_state(self) -> str:
        return self._fall_down_state

    @property
    def fall_down_recoverable(self) -> bool:
        return False

    @property
    def is_getting_up(self) -> bool:
        return self._getting_up

    def set_velocity(self, vx: float, vy: float, vyaw: float) -> None:
        self.moves.append((vx, vy, vyaw))
        self._kicking = False

    def kick(self, direction: float, power: float, ball_x: float, ball_y: float) -> None:
        self.kicks.append((direction, power))
        self._kicking = True

    def release_kick(self) -> None:
        self._kicking = False

    def request_mode(self, mode: str) -> None:
        pass

    def get_up(self) -> None:
        pass


def yaw_from_quat(q) -> float:
    w, x, y, z = q
    return math.atan2(2.0 * (w * z + x * y), 1.0 - 2.0 * (y * y + z * z))


def replay_intents_all_stop(frame: dict) -> bool | None:
    """我方（team_id=1）三台 commandIntents 是否同时 move.active=False 且 kick.active=False。

    返回 None 表示该帧没有完整 3 台 intent 记录（不能判定）。
    """
    intents = frame.get("commandIntents") or {}
    robots = intents.get("robots") or []
    if not isinstance(robots, list):
        return None
    my = [r for r in robots if r.get("team_id") == 1]
    if len(my) < 3:
        return None
    for r in my:
        move = r.get("move") or {}
        kick = r.get("kick") or {}
        if move.get("active") or kick.get("active"):
            return False
    return True


def run_playcheck(
    uuid: str,
    matches_dir: Path,
    frames: list[dict],
    manifest: dict,
    main_mod,
    limit_frames: int | None = None,
    show_traceback: bool = True,
) -> dict:
    from src.framework import types as T  # noqa: WPS433 - 延迟导入（依赖桩）

    recon = GameRecon(manifest)
    cfg_cls = importlib.import_module("src.framework.config").SoccerConfig
    config = cfg_cls(
        team_id=1,
        robot_names=("robot1", "robot2", "robot3"),
        opponent_robot_names=("robot4", "robot5", "robot6"),
    )
    player_mod = importlib.import_module("src.player")
    players = [player_mod.Player(pid, config, StubBackend(pid)) for pid in (1, 2, 3)]
    agent = object.__new__(main_mod.SoccerSimAgent)
    store = types.SimpleNamespace()
    agent.init_store(store)

    # 罚下→传送等待区后，replay 里位姿仍在；不需要额外处理。
    exceptions: list[dict] = []
    first_tb: str | None = None
    checked = 0
    for frame in frames:
        if limit_frames is not None and checked >= limit_frames:
            break
        t = float(frame.get("time", 0.0))
        ball_pos = frame.get("ball", {}).get("position") if frame.get("ball") else None
        ball_xy = (float(ball_pos[0]), float(ball_pos[1])) if ball_pos else None
        snap = recon.state_at(t, ball_xy)
        game_state = T.GameState[snap["state"]] if snap["state"] in T.GameState.__members__ else T.GameState.PLAYING
        set_play = T.SetPlay[snap["set_play"]] if snap["set_play"] in T.SetPlay.__members__ else T.SetPlay.NONE
        home_players = []
        for pid in range(1, 21):
            penalized = recon.penalty_of("home", pid, t)
            home_players.append(
                T.PlayerState(
                    penalty=T.Penalty.ILLEGAL_POSITIONING if penalized else T.Penalty.NONE,
                    secs_till_unpenalised=0,
                )
            )
        game = T.GameControlState(
            state=game_state,
            stopped=snap["stopped"],
            set_play=set_play,
            kicking_team=snap["kicking_team"],
            secondary_time=snap["secondary_time"],
            teams=(T.TeamState(team_number=1, players=tuple(home_players)), T.TeamState(team_number=2)),
        )
        teammates: dict[int, object] = {}
        opponents: dict[int, object] = {}
        for robot in frame.get("robots", []):
            pos = robot.get("basePosition")
            quat = robot.get("baseQuaternion")
            if not pos or not quat:
                continue
            state = T.RobotState(
                player_id=int(robot.get("playerNumber", 0)),
                pose=T.Pose2D(float(pos[0]), float(pos[1]), yaw_from_quat(quat)),
                last_seen_at=0.0,
            )
            if robot.get("side") == "home":
                teammates[state.player_id] = state
            else:
                opponents[state.player_id] = state
        if len(teammates) < 3 or ball_xy is None:
            continue
        ctx = T.Context(
            now=t,
            dt=1.0 / 30.0,
            team_id=1,
            field=T.ADULT_FIELD_DIMENSIONS,
            game=game,
            ball=T.BallState(x=ball_xy[0], y=ball_xy[1], last_seen_at=0.0),
            teammates=teammates,
            opponents=opponents,
        )
        for p in players:
            p.context = ctx
        checked += 1
        try:
            main_mod.SoccerSimAgent.play(ctx, players, store)
        except Exception as exc:  # noqa: BLE001 - 就是要抓全部
            if first_tb is None:
                first_tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
            exceptions.append(
                {
                    "t": t,
                    "exc_type": type(exc).__name__,
                    "exc_msg": str(exc),
                    "state": snap["state"],
                    "set_play": snap["set_play"],
                    "stopped": snap["stopped"],
                    "ball": ball_xy,
                    "all_stop_intents": replay_intents_all_stop(frame),
                }
            )
    # 冻结窗口（replay 观测）
    freeze_windows = []
    cur = None
    for idx, frame in enumerate(frames):
        t = float(frame.get("time", 0.0))
        ball_pos = frame.get("ball", {}).get("position") if frame.get("ball") else None
        ball_xy = (float(ball_pos[0]), float(ball_pos[1])) if ball_pos else None
        snap = recon.state_at(t, ball_xy)
        in_play = (
            snap["state"] == "PLAYING"
            and not snap["stopped"]
            and snap["set_play"] == "NONE"
            and snap["secondary_time"] <= 0.0
        )
        stopped = replay_intents_all_stop(frame)
        if in_play and stopped:
            if cur is None:
                cur = {"t0": t, "t1": t, "n": 1, "ball": ball_xy}
            else:
                cur["t1"] = t
                cur["n"] += 1
        else:
            if cur and cur["t1"] - cur["t0"] >= 1.0:
                freeze_windows.append(cur)
            cur = None
    if cur and cur["t1"] - cur["t0"] >= 1.0:
        freeze_windows.append(cur)

    return {
        "uuid": uuid,
        "frames": len(frames),
        "checked_frames": checked,
        "exceptions": exceptions,
        "first_traceback": first_tb,
        "freeze_windows": freeze_windows,
        "manifest": {
            "matchId": manifest.get("matchId"),
            "durationSeconds": manifest.get("durationSeconds"),
            "frameCount": manifest.get("frameCount"),
            "segments": len(manifest.get("segments", [])),
        },
    }


def print_report(result: dict, strategy_desc: str) -> None:
    m = result["manifest"]
    print(f"== replay playcheck: {result['uuid']} ==")
    print(
        f"   match={m['matchId']} dur={m['durationSeconds']}s "
        f"frames={m['frameCount']} segments={m['segments']}"
    )
    print(f"   strategy: {strategy_desc}")
    print(f"   play() 调用: {result['checked_frames']} 帧（跳过缺球/缺队友帧）")
    excs = result["exceptions"]
    if excs:
        print(f"   ❌ 异常: {len(excs)} 帧 ({100.0 * len(excs) / max(1, result['checked_frames']):.1f}%)")
        groups: dict[tuple[str, str], list[dict]] = {}
        for exc in excs:
            groups.setdefault((exc["exc_type"], exc["exc_msg"]), []).append(exc)
        for (etype, msg), items in sorted(groups.items(), key=lambda kv: -len(kv[1])):
            print(f"      {etype}: {msg}  ×{len(items)} 帧  (首个 t={items[0]['t']:.2f}s)")
        first = excs[0]
        print(
            f"   首个异常: t={first['t']:.3f}s state={first['state']} set={first['set_play']} "
            f"stopped={first['stopped']} ball={first['ball']}"
        )
        if result["first_traceback"]:
            print("   首个 traceback:")
            for line in result["first_traceback"].rstrip().splitlines()[-8:]:
                print("      " + line)
    else:
        print("   ✅ 异常: 0 帧")
    windows = result["freeze_windows"]
    total = sum(w["t1"] - w["t0"] for w in windows)
    frames_n = sum(w["n"] for w in windows)
    print(f"   replay 观测冻结窗口(≥1.0s, PLAYING 开放球权): {len(windows)} 段 / {total:.1f}s / {frames_n} 帧")
    for w in windows[:8]:
        ball = w.get("ball") or (float("nan"), float("nan"))
        print(f"      {w['t0']:7.2f}-{w['t1']:7.2f} {w['t1'] - w['t0']:5.1f}s ball=({ball[0]:6.2f},{ball[1]:6.2f})")
    if len(windows) > 8:
        print(f"      … 其余 {len(windows) - 8} 段见 --json")
    # 异常帧与冻结窗口的重合率
    if excs:
        inside = 0
        for exc in excs:
            for w in windows:
                if w["t0"] - 0.2 <= exc["t"] <= w["t1"] + 0.2:
                    inside += 1
                    break
        all_stop = sum(1 for exc in excs if exc["all_stop_intents"])
        print(
            f"   异常帧落在冻结窗口内: {inside}/{len(excs)} ({100.0 * inside / len(excs):.0f}%)"
            f"；异常帧上 replay 观测到三台全停: {all_stop}/{len(excs)}"
        )
    verdict = "PASS" if not excs else "FAIL"
    print(f"   verdict: {verdict}" + ("" if not excs else " — play() 必须整场 0 异常（runtime 捕获后会全队 stop）"))
    print()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="离线回放自检：逐帧调用策略 play()，抓异常/冻结窗口（提交前门禁）",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("uuids", nargs="+", help="回放 uuid（可多个）")
    parser.add_argument("--matches-dir", default=str(DEFAULT_MATCHES_DIR), help="回放归档目录")
    parser.add_argument("--src", default=None, help="策略 src 目录（默认仓库 src/）")
    parser.add_argument("--git-ref", default=None, help="改用 git 历史版本（如 5f60659），与 --src 二选一")
    parser.add_argument("--limit-frames", type=int, default=None, help="只跑前 N 帧（调试用）")
    parser.add_argument("--json", default=None, help="把结果写入 JSON 文件")
    args = parser.parse_args(argv)
    if args.src and args.git_ref:
        print("[replay_playcheck] --src 与 --git-ref 不能同时使用", file=sys.stderr)
        return 2
    matches_dir = Path(args.matches_dir).resolve()
    _, desc, main_mod = load_strategy(args.src, args.git_ref)
    if args.git_ref:
        print(f"[replay_playcheck] 使用 git 版本 src: {desc}")
    results = []
    failed = False
    for uuid in args.uuids:
        manifest = load_manifest(uuid, matches_dir)
        frames = load_frames(uuid, manifest, matches_dir)
        result = run_playcheck(uuid, matches_dir, frames, manifest, main_mod, args.limit_frames)
        print_report(result, desc)
        results.append(result)
        if result["exceptions"]:
            failed = True
    if args.json:
        with open(args.json, "w", encoding="utf-8") as fh:
            json.dump(results, fh, ensure_ascii=False, indent=1)
        print(f"[replay_playcheck] 结果已写入 {args.json}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
