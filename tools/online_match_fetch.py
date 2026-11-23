"""Fetch one online 3v3 match (detail + replay) and archive it locally.

Usage: python3 tools/online_match_fetch.py <match_uuid> [--out-dir docs/kb/online-matches]

Token: read from /tmp/.champ_token (JWT captured from logged-in champion page).
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.request

API = "https://api.booster.tech/api/v1/competition"


def token() -> str:
    with open("/tmp/.champ_token") as f:
        return f.read().strip()


def get(url: str, tok: str):
    req = urllib.request.Request(url, headers={"Authorization": "Bearer " + tok})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def get_bytes(url: str):
    with urllib.request.urlopen(url, timeout=60) as r:
        return r.read()


def main() -> int:
    uuid = sys.argv[1]
    out_dir = sys.argv[3] if len(sys.argv) > 3 else "docs/kb/online-matches"
    os.makedirs(out_dir, exist_ok=True)
    tok = token()
    detail = get(f"{API}/matches/{uuid}", tok)
    with open(os.path.join(out_dir, f"{uuid}.json"), "w") as f:
        json.dump(detail, f, ensure_ascii=False, indent=1)
    data = detail.get("data") or {}
    print("score", data.get("home_score"), ":", data.get("away_score"),
          "winner", data.get("winner"), "state", data.get("state"))
    replay = data.get("realtime_replay") or {}
    manifest_url = replay.get("manifest_url")
    if manifest_url:
        manifest = json.loads(get_bytes(manifest_url))
        with open(os.path.join(out_dir, f"{uuid}-manifest.json"), "w") as f:
            json.dump(manifest, f, ensure_ascii=False)
        print("manifest keys", sorted(manifest.keys())[:10])
        segs = manifest.get("segments") or []
        print("segments", len(segs))
        base = manifest_url.rsplit("/", 1)[0] + "/"
        seg_dir = os.path.join(out_dir, f"{uuid}-segments")
        os.makedirs(seg_dir, exist_ok=True)
        for i, seg in enumerate(segs):
            path = seg.get("path") or seg.get("url")
            if not path:
                continue
            url = path if path.startswith("http") else base + path
            try:
                raw = get_bytes(url)
                name = os.path.basename(path) or f"seg{i:06d}.jsonl.gz"
                with open(os.path.join(seg_dir, name), "wb") as f:
                    f.write(raw)
            except Exception as exc:  # noqa: BLE001
                print("seg fail", i, exc)
        print("segments saved to", seg_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
