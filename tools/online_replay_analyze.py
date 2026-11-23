"""Analyze a champion.booster.tech 3v3 replay (result stats + coordination metrics).

Usage:
  python3 tools/online_replay_analyze.py <replay.json> [--segments DIR] [--json OUT]

The replay JSON comes from the match's realtime_replay manifest; segments are
.jsonl.gz files with 10 Hz kinematic frames (ball position + per-robot basePosition).
"""
from __future__ import annotations

import argparse
import glob
import gzip
import json
import math
import os
import statistics
import sys


def load_frames(seg_dir: str):
    frames = []
    skipped = 0
    for path in sorted(glob.glob(os.path.join(seg_dir, "*.jsonl.gz"))):
        with gzip.open(path, "rt") as fd:
            for line in fd:
                line = line.strip()
                if not line:
                    continue
                try:
                    frames.append(json.loads(line))
                except json.JSONDecodeError:
                    # 线上 live replay 偶发半帧损坏(首个 segment 里一行是前半帧的残尾)。
                    # 跳过坏行即可，其余帧仍是完整的 10Hz 轨迹。
                    skipped += 1
    if skipped:
        print(f"[warn] skipped {skipped} malformed frame line(s)", file=sys.stderr)
    return frames


def analyze(replay: dict, seg_dir: str | None) -> dict:
    result = replay.get("result") or {}
    teams = (result.get("result") or result).get("teams") or {}
    match = replay.get("match") or {}
    out: dict = {
        "matchId": replay.get("matchId"),
        "durationSeconds": replay.get("durationSeconds"),
        "frameCount": replay.get("frameCount"),
        "events": len(replay.get("events") or []),
        "score": None,
        "teams": {},
    }
    for side, st in teams.items():
        stats = st.get("stats") or {}
        out["teams"][side] = {
            "name": st.get("teamName"),
            "score": st.get("score"),
            "fouls": (stats.get("fouls") or {}).get("total"),
            "foulsByReason": (stats.get("fouls") or {}).get("byReason"),
            "goals": ((stats.get("goals") or {}).get("total")),
            "invalidGoals": (stats.get("invalidGoals") or {}).get("total"),
            "oobAwarded": ((stats.get("outOfBounds") or {}).get("awarded") or {}).get("total"),
            "oobCaused": ((stats.get("outOfBounds") or {}).get("caused") or {}).get("total"),
        }
    out["score"] = {"home": (teams.get("home") or {}).get("score"),
                    "away": (teams.get("away") or {}).get("score")}
    out["winner"] = (result.get("result") or result).get("winner")
    if seg_dir and os.path.isdir(seg_dir):
        frames = load_frames(seg_dir)
        if frames:
            out["coordination"] = coordination(frames)
    return out


def coordination(frames: list[dict]) -> dict:
    """Compute per-side coordination metrics from 10 Hz frames."""
    metrics: dict = {}
    for side in ("home", "away"):
        pair_dists = []
        min_pair = []
        two_near_ball = []
        nearest_d = []
        poss = 0
        keeper_nearest = 0
        n = 0
        for fr in frames:
            robots = [r for r in fr.get("robots", []) if r.get("side") == side]
            ball = (fr.get("ball") or {}).get("position")
            if not robots or not ball or len(robots) < 3:
                continue
            n += 1
            pos = [r.get("basePosition") for r in robots]
            ds = []
            for i in range(len(pos)):
                for j in range(i + 1, len(pos)):
                    ds.append(math.dist(pos[i][:2], pos[j][:2]))
            pair_dists.append(sum(ds) / len(ds) if ds else 0.0)
            min_pair.append(min(ds) if ds else 0.0)
            ball_d = [math.dist(p[:2], ball[:2]) for p in pos]
            nearest_d.append(min(ball_d))
            two_near_ball.append(1 if sum(1 for d in ball_d if d < 1.5) >= 2 else 0)
        if n:
            metrics[side] = {
                "frames": n,
                "avg_pair_dist_m": round(statistics.mean(pair_dists), 2),
                "pct_min_pair_lt_1m": round(100 * sum(1 for d in min_pair if d < 1.0) / n, 1),
                "pct_two_within_1_5m_ball": round(100 * sum(two_near_ball) / n, 1),
                "avg_nearest_to_ball_m": round(statistics.mean(nearest_d), 2),
            }
    # ball position by half, share per side (both sides share the same ball track)
    in_home_half = 0
    total = 0
    for fr in frames:
        ball = (fr.get("ball") or {}).get("position")
        if not ball:
            continue
        total += 1
        if ball[0] < 0:
            in_home_half += 1
    if total:
        metrics["ball_in_home_half_pct"] = round(100 * in_home_half / total, 1)
    return metrics


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("replay")
    ap.add_argument("--segments", default=None)
    ap.add_argument("--json", default=None)
    args = ap.parse_args()
    replay = json.load(open(args.replay))
    seg = args.segments
    if seg is None:
        cand = args.replay.replace(".replay.json", "-segments")
        if os.path.isdir(cand):
            seg = cand
    out = analyze(replay, seg)
    print(json.dumps(out, ensure_ascii=False, indent=1))
    if args.json:
        with open(args.json, "w") as f:
            json.dump(out, f, ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
