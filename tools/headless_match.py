#!/usr/bin/env python3
"""Headless 3v3 match runner (no Booster Studio UI / no 3D rendering required).

Pipeline:
  1. ensure sim-lab container is running (create with the recorded docker spec if needed)
  2. ensure the headless simulator (app_in_container + game control) is up (/health on 38383)
  3. install the newest build/*.agent + BoosterAI agent into the container agent root
  4. launch football3v3_runner/run.py for both teams, wait until both agents are active
  5. POST /match/start, optionally set physics speed factor, monitor until the match is over
  6. archive status/result/events + /run/3v3_runner logs into docs/kb/logs/<tag>*.json

Usage:
  python3 tools/headless_match.py --tag headless-01
  python3 tools/headless_match.py --tag headless-02 --speed 2.0 --skip-install

Notes:
  * the container listens on 8788 (physics ws), 38383 (game control http) but we only talk
    to it through `docker exec`, so no host port publishing is needed.
  * first launch of the simulator needs ~1-2 min (colcon overlay build on first ever run).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
IMAGE = "booster-robotics-registry.cn-beijing.cr.aliyuncs.com/virtual-robot/virtual-robot:0.9.10-alpha-humble"
CONTAINER = "sim-lab"
STATICS = Path("/usr/share/booster-studio/resources/app/booster-native/statics")
HEADLESS = Path("/tmp/headless")
OURS = "com.example.lqinternalmatch"
AI = "com.booster.default3v3ai"
LOGS = REPO / "docs" / "kb" / "logs"
GC = "http://127.0.0.1:38383"


# ---------------------------------------------------------------- docker helpers
def run(cmd: list[str], timeout: float = 120, check: bool = False) -> subprocess.CompletedProcess:
    cp = subprocess.run(cmd, text=True, capture_output=True, timeout=timeout)
    if check and cp.returncode != 0:
        raise RuntimeError(f"{cmd} failed rc={cp.returncode}\nstdout={cp.stdout}\nstderr={cp.stderr}")
    return cp


def dexe(cmd: str, timeout: float = 120, check: bool = False) -> subprocess.CompletedProcess:
    return run(["docker", "exec", CONTAINER, "bash", "-lc", cmd], timeout=timeout, check=check)


def dexec_background(cmd: str, logfile: str) -> None:
    dexe(f"nohup bash -lc {json.dumps(cmd)} > {logfile} 2>&1 &", timeout=30, check=True)


def container_state() -> str:
    cp = run(["docker", "inspect", "-f", "{{.State.Status}}", CONTAINER], timeout=20)
    return cp.stdout.strip() if cp.returncode == 0 else "missing"


def ensure_container() -> None:
    state = container_state()
    if state == "running":
        return
    if state == "missing":
        log("creating sim-lab container")
        cmd = [
            "docker", "run", "-d", "--name", CONTAINER, "--privileged", "--shm-size=256m",
            "-v", f"{HEADLESS}/simsrc:/usr/local/booster_robot/booster_robocup_sim",
            "-v", f"{HEADLESS}/library:/opt/booster-studio/library",
            "-v", f"{HEADLESS}/agent_data:/opt/booster/booster_agent_data",
            "-v", f"{HEADLESS}/runner:/match",
            "-v", f"{HEADLESS}/scripts:/scripts:ro",
            "-v", f"{REPO}/build:/agents:ro",
            "-v", f"{STATICS}/ai-agent:/agents-ai:ro",
            "-e", "BOOSTER_SIM_LIBRARY_ROOT=/opt/booster-studio/library",
            "-e", "BOOSTER_EMBEDDED_MOTION=1",
            "-e", "ROS_DOMAIN_ID=0",
            "-e", "FASTRTPS_DEFAULT_PROFILES_FILE=/opt/booster/BoosterRos2/fastdds_profile.xml",
            IMAGE, "bash", "-lc", "sleep infinity",
        ]
        run(cmd, timeout=120, check=True)
    else:
        log(f"starting container (was {state})")
        run(["docker", "start", CONTAINER], timeout=60, check=True)
    time.sleep(2)


# ---------------------------------------------------------------- simulator
def health() -> dict | None:
    cp = dexe(f"curl -s --max-time 5 {GC}/health", timeout=20)
    if cp.returncode != 0 or not cp.stdout.strip():
        return None
    try:
        return json.loads(cp.stdout)
    except json.JSONDecodeError:
        return None


def wait_health(timeout: float = 240) -> None:
    t0 = time.time()
    while time.time() - t0 < timeout:
        h = health()
        if h and h.get("ready"):
            log(f"simulator ready ({int(time.time() - t0)}s): {h}")
            return
        time.sleep(3)
    raise RuntimeError("simulator /health never became ready")


def ensure_sim() -> None:
    h = health()
    if h and h.get("ready"):
        log("simulator already up")
        return
    log("starting headless simulator")
    dexec_background("/scripts/launch_sim.sh", "/tmp/sim.log")
    wait_health(300)


def stop_agents() -> None:
    dexe("pkill -f 'match/run.py' 2>/dev/null; pkill -f supervisor.py 2>/dev/null; "
         "pkill -f pyagent_x86_64 2>/dev/null; sleep 1; rm -f /match/*.ready; rm -rf /run/3v3_runner",
         timeout=60)


def newest_agent_package() -> Path:
    pkgs = sorted((REPO / "build").glob("*.agent"), key=lambda p: p.stat().st_mtime)
    if not pkgs:
        raise RuntimeError("no .agent package in build/")
    return pkgs[-1]


def install_agents(pkg: Path | None) -> None:
    if pkg is not None:
        log(f"installing agent package {pkg.name}")
        run(["docker", "cp", str(pkg), f"{CONTAINER}:/tmp/our.agent"], timeout=120, check=True)
        dexe("cd /match && python3 install_agent_package.py /tmp/our.agent "
             "--install-root /opt/booster/booster_agent_data/data/agents/extract", timeout=180, check=True)
    log("installing BoosterAI agent package")
    dexe("cd /match && python3 install_agent_package.py /agents-ai/football3v3/com.booster.default3v3ai.agent "
         "--install-root /opt/booster/booster_agent_data/data/agents/extract", timeout=180, check=True)


# ---------------------------------------------------------------- match control
def start_runner(timeout: float = 300) -> None:
    # 上一场结束后的 /tmp/booster_agent* 残留会让新 sandbox 启动即退出
    # （run.py 报 "agent sandbox exited before lifecycle activation"），先清掉。
    dexe("rm -rf /tmp/booster_agent /tmp/booster_agent_deploy; pkill -f '[p]ython3 -u run.py' || true", timeout=30)
    log("starting football3v3_runner for both teams (agent activation takes ~95s)")
    dexec_background(f"cd /match && python3 -u run.py --teams {OURS} {AI}", "/tmp/match_run.log")
    t0 = time.time()
    while time.time() - t0 < timeout:
        cp = dexe("tail -c 4000 /tmp/match_run.log; ls /match/*.ready 2>/dev/null", timeout=30)
        out = cp.stdout
        if "all 3v3 agents are active" in out or "/match/ready" in out:
            log(f"both agents active after {int(time.time() - t0)}s")
            return
        if "timed out waiting for agent" in out:
            raise RuntimeError("agent activation timed out:\n" + out[-2000:])
        time.sleep(5)
    raise RuntimeError("agents never became active:\n" + dexe("tail -c 3000 /tmp/match_run.log").stdout[-2000:])


def wait_match_playing(timeout: float = 60.0) -> None:
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            raw = dexe(f"curl -s --max-time 3 {GC}/status", timeout=20).stdout
            st = json.loads(raw)
            m = st.get("match") or {}
            game = m.get("game") or {}
            if m.get("status") == "active" and game.get("state") in ("ready", "set", "playing"):
                log(f"match active: state={game.get('state')}")
                return
        except Exception:
            pass
        time.sleep(2)
    log("warning: match did not become active before monitor; continuing anyway")


def start_match() -> dict:
    cp = dexe(f"curl -s -X POST {GC}/match/start -H 'content-type: application/json' -d '{{}}'", timeout=30, check=True)
    return json.loads(cp.stdout)


def set_speed(factor: float) -> None:
    script = f"""import asyncio, json, websockets
async def main():
    async with websockets.connect('ws://127.0.0.1:8788') as ws:
        await ws.send(json.dumps({{'type':'command','command':'set_speed','params':{{'speed_factor': {factor}}}}}) )
        await ws.send('subscribe:simulation_state')
        for _ in range(10):
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=2)
            except Exception:
                continue
            if isinstance(msg, bytes) and len(msg) > 8:
                print('sent speed_factor={factor}')
                return
asyncio.run(main())
"""
    Path("/tmp/hl_setspeed.py").write_text(script)
    run(["docker", "cp", "/tmp/hl_setspeed.py", f"{CONTAINER}:/tmp/hl_setspeed.py"], timeout=60, check=True)
    cp = dexe("/usr/local/booster_robot/booster_robocup_sim/.venv/bin/python /tmp/hl_setspeed.py", timeout=60)
    log(f"set_speed({factor}) -> {cp.stdout.strip() or cp.stderr.strip()}")


def monitor(tag: str, timeout: float) -> dict:
    mon = REPO / "tools" / "headless_monitor.py"
    run(["docker", "cp", str(mon), f"{CONTAINER}:/tmp/headless_monitor.py"], timeout=60, check=True)
    dexec_background(f"python3 -u /tmp/headless_monitor.py {tag} /tmp/{tag}.json", f"/tmp/monhl_{tag}.log")
    t0 = time.time()
    while time.time() - t0 < timeout:
        cp = dexe(f"tail -2 /tmp/monhl_{tag}.log; test -f /tmp/{tag}.json && echo ARCHIVED", timeout=30)
        if "ARCHIVED" in cp.stdout:
            break
        time.sleep(10)
    else:
        log("monitor timeout; forcing /match/end")
        dexe(f"curl -s -X POST {GC}/match/end -H 'content-type: application/json' -d '{{}}'", timeout=30)
        for _ in range(30):
            if dexe(f"test -f /tmp/{tag}.json && echo OK", timeout=20).stdout.find("OK") >= 0:
                break
            time.sleep(5)
    LOGS.mkdir(parents=True, exist_ok=True)
    out = LOGS / f"{tag}.json"
    run(["docker", "cp", f"{CONTAINER}:/tmp/{tag}.json", str(out)], timeout=120, check=True)
    log(f"archived -> {out}")
    # runner logs (agent logs, sandbox logs)
    runner_dir = LOGS / f"{tag}-runner"
    subprocess.run(["rm", "-rf", str(runner_dir)], check=False)
    run(["docker", "cp", f"{CONTAINER}:/run/3v3_runner", str(runner_dir)], timeout=180)
    log(f"runner logs -> {runner_dir}")
    with open(out) as f:
        return json.load(f)


# ---------------------------------------------------------------- reporting
def summarize(doc: dict) -> None:
    res = doc.get("result") or {}
    if "score" not in res and "result" in res:
        res = res["result"] or res
    print("\n=== MATCH SUMMARY ===")
    print(json.dumps({k: res.get(k) for k in ("score", "winner", "endReason", "duration", "warnings")
                      if res.get(k) is not None}, ensure_ascii=False, indent=1))
    print(f"wall seconds: {doc.get('duration_wall_s')}")


def log(msg: str) -> None:
    print(f"[headless] {msg}", flush=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True)
    ap.add_argument("--speed", type=float, default=1.0, help="physics speed factor (1.0 = realtime target)")
    ap.add_argument("--skip-install", action="store_true")
    ap.add_argument("--skip-runner-check", action="store_true")
    ap.add_argument("--timeout", type=float, default=900, help="max wall seconds for the match")
    args = ap.parse_args()

    ensure_container()
    ensure_sim()
    stop_agents()
    if args.skip_install:
        log("skip agent install")
    else:
        install_agents(None if args.skip_install else newest_agent_package())
    start_runner()
    if not args.skip_runner_check:
        pass
    st = start_match()
    g = st.get("game") or {}
    log(f"match started: state={g.get('state')} timeRemaining={g.get('timeRemaining')}")
    if abs(args.speed - 1.0) > 1e-6:
        time.sleep(2)
        set_speed(args.speed)
    # 等比赛真正进入 playing 再启动 monitor：/match/start 后有一段 ready 阶段，
    # 若立即启动 monitor 可能读到上一场遗留的 finished 状态而提前归档（headless-04 踩过）。
    wait_match_playing()
    doc = monitor(args.tag, args.timeout)
    summarize(doc)
    # analyze
    cp = run([sys.executable, str(REPO / "tools" / "analyze_match.py"), str(LOGS / f"{args.tag}.json")],
             timeout=120)
    print(cp.stdout[-4000:] if cp.stdout else cp.stderr[-2000:])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
