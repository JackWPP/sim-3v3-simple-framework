"""Create an Arena 3v3 challenge via API (auto-match or specific opponent).

Usage:
  python3 tools/online_challenge.py auto            # 自动匹配（推荐）
  python3 tools/online_challenge.py player <player_uuid>

The server returns match_uuid; poll GET /matches/{uuid} until state==finished.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.request
import uuid

API = "https://api.booster.tech/api/v1/competition"


def token() -> str:
    with open("/tmp/.champ_token") as f:
        return f.read().strip()


def get(url: str, tok: str):
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + tok})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def post(url: str, payload: dict, tok: str):
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + tok},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def me(tok: str) -> dict:
    return get(f"{API}/player/me", tok).get("data") or {}


def create(tok: str, opponent: str | None) -> dict:
    arena = get(f"{API}/arenas/3v3", tok).get("data") or {}
    cost = arena.get("discount_cost_display") or "10.000000"
    if opponent is None:
        # 自动匹配：服务端按积分匹配，并返回 match_uuid。
        body = {"idempotency_key": str(uuid.uuid4()), "expected_cost_display": cost}
    else:
        body = {
            "opponent_player_id": opponent,
            "idempotency_key": str(uuid.uuid4()),
            "expected_cost_display": cost,
        }
    return post(f"{API}/arenas/3v3/challenges", body, tok)


def main() -> int:
    tok = token()
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    mode = sys.argv[1]
    opponent = sys.argv[2] if len(sys.argv) > 2 and mode == "player" else None
    res = create(tok, opponent)
    print(json.dumps(res, ensure_ascii=False)[:600])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
