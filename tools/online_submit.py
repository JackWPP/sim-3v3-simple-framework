"""Submit a built .agent to champion.booster.tech as the default competition code.

Usage:
  python3 tools/online_submit.py build/com.example.lqinternalmatch-1.1.0.agent \
      --display-name com.example.lqinternalmatch-v2.1 [--no-default]

Reads the JWT from /tmp/.champ_token (see docs/kb/online-loop.md).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import urllib.request

API = "https://api.booster.tech/api/v1/competition/3v3"


def token() -> str:
    with open("/tmp/.champ_token") as f:
        return f.read().strip()


def post(url: str, payload: dict, tok: str):
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + tok},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("agent")
    ap.add_argument("--display-name", default=None)
    ap.add_argument("--no-default", action="store_true")
    args = ap.parse_args()
    data = open(args.agent, "rb").read()
    size = len(data)
    sha = hashlib.sha256(data).hexdigest()
    fname = os.path.basename(args.agent)
    if not fname.endswith(".agent"):
        fname = fname + ".agent"  # API 要求 filename 以 .agent 结尾
    name = args.display_name or os.path.splitext(fname)[0]
    tok = token()
    up = post(f"{API}/codes/upload-url", {"filename": fname, "size": size}, tok)["data"]
    req = urllib.request.Request(
        up["upload_url"], data=data,
        headers={"Content-Type": "application/octet-stream"}, method="PUT",
    )
    with urllib.request.urlopen(req, timeout=180) as r:
        assert 200 <= r.status < 300, r.status
    res = post(
        f"{API}/codes",
        {
            "code_file_key": up["file_key"],
            "file_size": size,
            "sha256": sha,
            "display_name": name,
            "set_default": not args.no_default,
        },
        tok,
    )
    print(json.dumps({"size": size, "sha256": sha, "result": res.get("data")},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
