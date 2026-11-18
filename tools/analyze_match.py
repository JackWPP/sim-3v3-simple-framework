"""Summarize an archived 3v3 match JSON (docs/kb/logs/*.json) into a compact report.

Usage: python3 tools/analyze_match.py docs/kb/logs/baseline-01.json [--md]
NOTE: for Studio virtual matches our agent runs as team_id 1 = home side
(robot1/robot2/robot3); the opponent Booster AI is team2 = away (robot4-6).
Confirmed from /run/3v3_runner/team_1/sandbox.log inside the sim container.
"""
import json, sys
from pathlib import Path

EVENT_SKIP = {"ball_touch", "ball_free", "state_changed",
              "ball_placement_started", "ball_placement_complete"}


def load(path):
    d = json.loads(Path(path).read_text())
    status = d.get("status") or {}
    raw = status.get("raw") or {}
    match = raw.get("match") or {}
    logs = d.get("logs") or []
    return status, raw, match, logs


def fmt_meas(ev):
    out = []
    for m in (ev or {}).get("measurements") or []:
        v = m.get("value")
        v = round(v, 2) if isinstance(v, float) else v
        out.append(f"{m.get('name')}={v}{m.get('unit', '')} ({m.get('operator')} {m.get('threshold')})")
    return ", ".join(out)


def main():
    path = sys.argv[1]
    md = "--md" in sys.argv
    status, raw, match, logs = load(path)
    score = status.get("score") or match.get("score")
    print(f"== MATCH {match.get('matchId', '?')} status={match.get('status')} final={match.get('isFinal')}")
    print(f"   score={score} winner={match.get('winner')} endReason={match.get('endReason')} "
          f"duration={match.get('durationSeconds')}")
    print(f"   teams={json.dumps(match.get('teams'), ensure_ascii=False)[:300]}")
    warnings = match.get("warnings") or []
    if warnings:
        print(f"   warnings: {json.dumps(warnings, ensure_ascii=False)[:500]}")

    # goal / penalty timeline
    print("\n== EVENTS (goals / penalties / warnings)")
    goals, pens = [], []
    for e in logs:
        ty, a = e.get("type"), e.get("actor") or {}
        ev, oc, g = e.get("evidence") or {}, e.get("outcome") or {}, e.get("game") or {}
        if ty in EVENT_SKIP:
            continue
        el = e.get("timing", {}).get("timeRemaining")
        el = round(600 - el, 1) if isinstance(el, (int, float)) else "?"
        sc = e.get("score") or {}
        print(f"  +{el:>6}s {ty:<22} actor={a.get('side', '-'):4}/{a.get('robotName', '-'):<7} "
              f"rule={ev.get('ruleId', '-')}/{ev.get('subRuleId', '-')} "
              f"score={sc.get('home')}:{sc.get('away')} state={g.get('state')} set={g.get('setPlay')}")
        if ev.get("summary"):
            print(f"      summary: {ev['summary']}")
        m = fmt_meas(ev)
        if m:
            print(f"      meas: {m}")
        if oc.get("penalty") or oc.get("seconds"):
            print(f"      outcome: penalty={oc.get('penalty')} seconds={oc.get('seconds')}")
        if ty == "goal":
            goals.append(e)
        if ty == "penalty":
            pens.append(e)

    # touches per side
    touch = {"home": 0, "away": 0, "?": 0}
    for e in logs:
        if e.get("type") == "ball_touch":
            touch[(e.get("actor") or {}).get("side") or "?"] += 1
    print(f"\n== TOUCHES {touch}")
    print(f"== GOALS home={sum(1 for g in goals if (g.get('actor') or {}).get('side')=='home')} "
          f"away={sum(1 for g in goals if (g.get('actor') or {}).get('side')=='away')}")
    print(f"== PENALTIES home={sum(1 for p in pens if (p.get('actor') or {}).get('side')=='home')} "
          f"away={sum(1 for p in pens if (p.get('actor') or {}).get('side')=='away')}")
    for p in pens:
        ev = p.get("evidence") or {}
        print(f"   - {ev.get('ruleId')}/{ev.get('subRuleId')} actor={(p.get('actor') or {}).get('side')} "
              f"robot={(p.get('actor') or {}).get('robotName')} "
              f"tv={p.get('timing', {}).get('timeRemaining')}")


if __name__ == "__main__":
    main()
