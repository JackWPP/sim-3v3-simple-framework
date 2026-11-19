#!/usr/bin/env python3
"""Monitor a headless 3v3 match and archive it in the standard schema.

Runs *inside* the sim container (game control HTTP is on 127.0.0.1:38383) or on the
host if the port is published.

Usage (inside container):
    python3 /tmp/headless_monitor.py <tag> [/tmp/<tag>.json]

Output schema matches docs/kb/logs/<iteration>.json used by tools/analyze_match.py:
    {tag, started_at, archived_at, duration_wall_s,
     status: {gameControl, match, game, raw:{gameControl, match, game}, score},
     logs: [events...]}
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request

GC = "http://127.0.0.1:38383"


def get(path: str):
    with urllib.request.urlopen(GC + path, timeout=20) as r:
        return json.loads(r.read().decode())


def main() -> int:
    tag = sys.argv[1] if len(sys.argv) > 1 else "headless"
    out = sys.argv[2] if len(sys.argv) > 2 else f"/tmp/{tag}.json"
    interval = 10
    t0 = time.monotonic()
    started_at = time.strftime("%Y-%m-%dT%H:%M:%S")
    prev = None
    while True:
        try:
            st = get("/status")
        except Exception as exc:  # noqa: BLE001
            print("poll error:", exc, flush=True)
            time.sleep(2)
            continue
        game = st.get("game") or {}
        match = st.get("match") or {}
        score = match.get("score") or {}
        rem = game.get("timeRemaining")
        wall = time.monotonic() - t0
        ratio = float("nan")
        if isinstance(rem, (int, float)) and prev and isinstance(prev[1], (int, float)):
            ratio = (prev[1] - rem) / max(1e-6, wall - prev[2])
        prev = (score, rem, wall)
        print("wall=%.0fs state=%s rem=%s score=%s:%s ratio=%.2f" % (
            wall, game.get("state"), None if rem is None else round(rem, 1),
            score.get("home"), score.get("away"), ratio), flush=True)
        if match.get("isFinal") or game.get("state") == "finished":
            break
        if wall > 1800:
            print("monitor timeout", flush=True)
            break
        time.sleep(interval)

    try:
        status = get("/status")
    except Exception as exc:  # noqa: BLE001
        status = {"error": str(exc)}
    try:
        events = get("/events/history?limit=5000")
    except Exception as exc:  # noqa: BLE001
        events = {"error": str(exc)}
    gc = status.get("gameControl") or {}
    match = status.get("match") or {}
    game = status.get("game") or {}
    doc = {
        "tag": tag,
        "started_at": started_at,
        "archived_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "duration_wall_s": round(time.monotonic() - t0, 1),
        "status": {
            "gameControl": gc,
            "match": match,
            "game": game,
            "score": match.get("score"),
            "raw": {"gameControl": gc, "match": match, "game": game},
        },
        "logs": events.get("events") if isinstance(events, dict) else events,
    }
    with open(out, "w") as f:
        json.dump(doc, f)
    print("archived ->", out, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
