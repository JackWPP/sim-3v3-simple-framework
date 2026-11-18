"""Watch the running 3v3 match and archive the result + referee log.

Polls via tools/bcmd.py (Studio DevTools bridge). Saves one JSON file with:
  {status: <last get3v3MatchStatus out>, logs: <get3v3MatchLogs out>}

Usage: python3 tools/matchw.py [--interval 10] [--out docs/kb/logs/match.json]
"""
import argparse, json, subprocess, sys, time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def bcmd(cmd, args=None, wait=60):
    argv = [sys.executable, str(ROOT / "tools" / "bcmd.py"), "--wait", str(wait), cmd]
    if args is not None:
        argv.append(json.dumps(args))
    out = subprocess.run(argv, capture_output=True, text=True, timeout=wait + 30).stdout.strip()
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return {"ok": False, "raw": out}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", type=float, default=10.0)
    ap.add_argument("--out", default="docs/kb/logs/last-match.json")
    ap.add_argument("--max-wait", type=float, default=900.0)
    a = ap.parse_args()

    t0 = time.time()
    last = None
    while time.time() - t0 < a.max_wait:
        st = bcmd("booster.agent.get3v3MatchStatus", {"includeRaw": True}, wait=40)
        o = st.get("out") or {}
        raw = o.get("raw") or {}
        match = raw.get("match") or {}
        game = raw.get("game") or {}
        state = o.get("state")
        score = o.get("score")
        remaining = game.get("timeRemaining")
        print(f"[{time.time()-t0:6.1f}s] state={state} score={score} "
              f"gameState={game.get('state')} remain={remaining}", flush=True)
        last = st
        if match.get("isFinal") or (state in ("finished", "ended")):
            break
        time.sleep(a.interval)

    logs = bcmd("booster.agent.get3v3MatchLogs", {"limit": 1000, "includeRaw": True}, wait=90)
    result = {
        "archived_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "status": (last or {}).get("out"),
        "logs": (logs.get("out") or {}).get("logs"),
    }
    out = ROOT / a.out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=1))
    print(f"saved {out} ({len(result['logs'] or [])} events)")


if __name__ == "__main__":
    main()
