"""One-command iteration loop: build -> run -> start 3v3 match -> archive -> summary.

Uses the Studio DevTools bridge (http://127.0.0.1:8765, see tools/bcmd.py).

Usage:
    python3 tools/matchrun.py --tag iteration-02
    python3 tools/matchrun.py --tag iteration-02 --skip-build --skip-run

Steps:
    1. booster.agent.build        (compile strategy -> .agent)
    2. booster.agent.run          (deploy + start virtual robot/simulator, ~2-3 min)
    3. poll get3v3MatchStatus until prompt / GameControl is ready
    4. booster.agent.start3v3Match
    5. watch until match finished (max --max-wait seconds)
    6. archive status+logs to docs/kb/logs/<tag>.json
    7. docker cp the simulator /run/3v3_runner dir (our team's log/data) to
       docs/kb/logs/<tag>-runner/ (container exits right after the match)
    8. run analyze_match.py (also saved next to the archive as <tag>-summary.txt)

The full match takes ~11-13 real minutes (600 s sim + ready/placement overhead).
Keep this process in background and poll its output.
"""
import argparse
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASE = "http://127.0.0.1:8765"
WORKSPACE = str(ROOT)
ROBOT_SN = "h5t6r"
START_SCENE = "football_match_pitch_6_K1"


def _post(path, obj):
    req = urllib.request.Request(
        BASE + path,
        data=json.dumps(obj).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def _get(path, timeout=40):
    with urllib.request.urlopen(BASE + path, timeout=timeout) as r:
        return json.loads(r.read())


def bcmd(cmd, args=None, wait=60.0):
    """Send one command through the bridge and wait for its result."""
    rid = _post("/cmd", {"cmd": cmd, "args": args})["id"]
    deadline = time.time() + wait
    while True:
        try:
            res = _get(f"/result?id={rid}")
        except Exception:
            time.sleep(0.5)
            if time.time() > deadline:
                return {"ok": False, "err": "timeout"}
            continue
        if res.get("ready"):
            return res["result"]
        if time.time() > deadline:
            return {"ok": False, "err": "timeout", "id": rid}
        time.sleep(0.2)


def status_row(st):
    """Normalise get3v3MatchStatus output into a small dict for logging."""
    o = st.get("out") or {}
    raw = o.get("raw") or {}
    match = raw.get("match") or {}
    game = raw.get("game") or {}
    return {
        "ok": o.get("ok", st.get("ok")),
        "state": o.get("state"),
        "score": o.get("score"),
        "match_is_final": bool(match.get("isFinal")),
        "game_state": game.get("state"),
        "time_remaining": game.get("timeRemaining"),
        "set_play": game.get("setPlay"),
        "secondary_time": game.get("secondaryTime"),
        "kicking_side": game.get("kickingSide"),
        "teams": raw.get("teams"),
        "error": o.get("error") or st.get("err"),
    }


def wait_match_ready(max_wait=240.0):
    t0 = time.time()
    while time.time() - t0 < max_wait:
        st = bcmd("booster.agent.get3v3MatchStatus", {"includeRaw": True}, wait=40)
        row = status_row(st)
        print(f"  [ready-check {time.time()-t0:5.1f}s] {row}", flush=True)
        if row["ok"] and row["state"] in ("initial", "ready", "set", "playing", "finished", "ended"):
            return row
        time.sleep(5)
    return None


def wait_match_finish(max_wait=900.0, interval=10.0):
    t0 = time.time()
    last = None
    while time.time() - t0 < max_wait:
        st = bcmd("booster.agent.get3v3MatchStatus", {"includeRaw": True}, wait=40)
        row = status_row(st)
        last = st
        remain = row.get("time_remaining")
        print(
            f"  [{time.time()-t0:6.1f}s] state={row['state']} score={row['score']} "
            f"game={row['game_state']} remain={remain} final={row['match_is_final']}",
            flush=True,
        )
        if row["match_is_final"] or row["state"] in ("finished", "ended"):
            break
        if not row["ok"]:
            time.sleep(interval)
            continue
        time.sleep(interval)
    return last


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", required=True, help="iteration name, e.g. iteration-02")
    ap.add_argument("--skip-build", action="store_true")
    ap.add_argument("--skip-run", action="store_true")
    ap.add_argument("--max-wait", type=float, default=900.0)
    ap.add_argument("--out-dir", default="docs/kb/logs")
    a = ap.parse_args()

    started_at = time.strftime("%Y-%m-%dT%H:%M:%S")
    print(f"== {a.tag} ==", flush=True)

    if not a.skip_build:
        print("[1/5] build", flush=True)
        r = bcmd("booster.agent.build", {"workspacePath": WORKSPACE}, wait=300)
        build_out = r.get("out") or {}
        print(f"      build -> {json.dumps(build_out or r, ensure_ascii=False)[:500]}", flush=True)
        build_ok = bool(
            (isinstance(build_out, dict) and (build_out.get("ok") or build_out.get("agentId")))
            or r.get("ok")
        )
        if not build_ok:
            print("BUILD FAILED, abort", flush=True)
            return 1

    if not a.skip_run:
        # 先 stop 上一次 run:否则 Studio 复用旧 simulator/game-control,新 agent 可能
        # 连不上已结束的 run,表现为 context 全空(game=None/ball=None/teammates 0/3),
        # 策略完全不动(iteration-06 踩坑)。
        print("[2/5] run (stop stale run, deploy + start simulator)", flush=True)
        try:
            bcmd("booster.agent.stop", {"workspacePath": WORKSPACE}, wait=90)
        except Exception as exc:  # noqa: BLE001 - 没有在跑时 stop 会失败,忽略
            print(f"      stop (ignored): {exc}", flush=True)
        r = bcmd("booster.agent.run", {"workspacePath": WORKSPACE}, wait=600)
        out = r.get("out") or r
        print(f"      run -> {json.dumps(out, ensure_ascii=False)[:500]}", flush=True)
        if isinstance(out, dict) and out.get("run_result") not in (None, "success"):
            print("RUN FAILED, abort", flush=True)
            return 1

    print("[3/5] wait for match prompt / GameControl", flush=True)
    row = wait_match_ready(max_wait=240)
    if row is None:
        print("MATCH PROMPT NOT READY, abort", flush=True)
        return 1

    print("[4/5] start 3v3 match", flush=True)
    r = bcmd(
        "booster.agent.start3v3Match",
        {
            "workspacePath": WORKSPACE,
            "robotSerialNumber": ROBOT_SN,
            "selectedScene": START_SCENE,
        },
        wait=120,
    )
    print(f"      start -> {json.dumps(r.get('out') or r, ensure_ascii=False)[:500]}", flush=True)

    print(f"[5/5] watch match (max {a.max_wait:.0f}s)", flush=True)
    last = wait_match_finish(max_wait=a.max_wait)

    logs = bcmd("booster.agent.get3v3MatchLogs", {"limit": 2000, "includeRaw": True}, wait=120)
    logs_out = logs.get("out") or {}
    result = {
        "tag": a.tag,
        "started_at": started_at,
        "archived_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "status": (last or {}).get("out"),
        "logs": logs_out.get("logs") if isinstance(logs_out, dict) else None,
    }
    out = ROOT / a.out_dir / f"{a.tag}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=1))

    event_count = len(result["logs"] or [])
    print(f"archived {out} ({event_count} events)", flush=True)

    # 仿真容器在比赛结束后会立刻 Exited(143),但还能 docker cp;把整份 runner
    # 目录(含我方 team_1 的 sandbox.log/data)拷出来,便于复盘 agent 侧行为。
    runner_dir = ROOT / a.out_dir / f"{a.tag}-runner"
    try:
        if runner_dir.exists():
            import shutil
            shutil.rmtree(runner_dir)
        r = subprocess.run(
            ["docker", "cp", f"{ROBOT_SN}-k1:/run/3v3_runner", str(runner_dir)],
            capture_output=True, text=True, timeout=60,
        )
        if r.returncode == 0:
            files = sum(1 for _ in runner_dir.rglob("*") if _.is_file())
            print(f"archived runner logs -> {runner_dir} ({files} files)", flush=True)
        else:
            print(f"runner archive skipped: {r.stderr.strip()[:200]}", flush=True)
    except Exception as exc:  # noqa: BLE001 - archive must never fail the run
        print(f"runner archive failed: {exc}", flush=True)

    # quick summary with the existing analyzer(同时存档一份,便于回看/填 iterations.md)
    summary = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "analyze_match.py"), str(out)],
        check=False, capture_output=True, text=True,
    )
    text = (summary.stdout or "") + (summary.stderr or "")
    summary_path = out.with_name(f"{a.tag}-summary.txt")
    summary_path.write_text(text)
    print(f"summary -> {summary_path}", flush=True)
    print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
