"""A/B runner for the 3v3 Arena (v5.0 final vs v4.5b control) — dry-run by default.

Subcommands:
  plan
      Print the full 4-match A/B sequence with the exact submit/set_default/challenge
      commands and the expected credit spend (4 x 10 = 40 credits).

  submit <pkg.agent> --display-name <name> [--no-default]
      Upload a .agent package (upload-url -> PUT -> codes). Without --no-default it
      becomes the default competition code. Costs 0 credits.

  set_default <pkg.agent> --display-name <name>
      Re-submit the same package with set_default=true (switch the active arm).

  match <opponent_player_id> --tag <tag> [--yes] [--timeout-min 20]
      Create a FREE_BATTLE 3v3 challenge against the given opponent, poll until the
      match finishes, then archive it with tools/online_match_fetch.py and print the
      /tmp/ra/ab_row.py readout row + /tmp/ra/ab_valid.py validity verdict.
      DRY-RUN BY DEFAULT: prints the request that would be sent and the estimated
      cost, and does NOT create the challenge. Pass --yes to actually spend credits.

  status
      Show credit balance (best effort), current default code version and match count.

Token: read from /tmp/.champ_token (JWT captured from the logged-in champion page).
Refresh when expired:
  cd /tmp && node /tmp/cdp.js eval 'localStorage.getItem("booster_auth_token")' \\
      2>/dev/null | tr -d '"' > /tmp/.champ_token
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid

API = "https://api.booster.tech/api/v1/competition"
CODES_API = API + "/3v3"
TOKEN_FILE = "/tmp/.champ_token"
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CANDIDATES = os.path.join(REPO, "build", "candidates")
ARCHIVE_DIR = os.path.join(REPO, "docs", "kb", "online-matches")
AB_ROW = "/tmp/ra/ab_row.py"
AB_VALID = "/tmp/ra/ab_valid.py"

# A/B 配置（2026-11-24 阶段冻结；改名前先同步 docs/kb/reviews/v5-ab-readout.md）
CONTROL_PKG = os.path.join(CANDIDATES, "v4.5b-6fb30100.agent")
CONTROL_NAME = "com.example.lqinternalmatch-v4.5b-ctrl"
TEST_PKG = os.path.join(CANDIDATES, "v5.0-final2-172da34d.agent")
TEST_NAME = "com.example.lqinternalmatch-v5.0-final2"
OPP_0707 = "19b7f706-c6e2-48ac-9e19-0e5310ad0bf1"
OPP_ZHANG = "433ab70b-e502-4fbb-88d7-b72cfcd93921"
OPP_NAMES = {OPP_0707: "0707", OPP_ZHANG: "张原硕"}
COST_DISPLAY = "10.000000"

ARMS = {"A": ("v4.5b-control", CONTROL_PKG, CONTROL_NAME),
        "B": ("v5.0-final2", TEST_PKG, TEST_NAME)}


# --------------------------------------------------------------------------- HTTP
def token() -> str:
    try:
        with open(TOKEN_FILE) as f:
            tok = f.read().strip()
    except FileNotFoundError:
        halt("missing token file /tmp/.champ_token")
    if not tok:
        halt("empty token file /tmp/.champ_token")
    return tok


def api(method: str, path: str, payload: dict | None = None, tok: str | None = None,
        timeout: int = 60):
    url = path if path.startswith("http") else API + path
    tok = tok or token()
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {"Authorization": "Bearer " + tok}
    if payload is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read()
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:400]
        if e.code == 401:
            halt("401 unauthorized — refresh /tmp/.champ_token from the champion page")
        halt(f"HTTP {e.code} on {method} {path}: {detail}")
    return json.loads(body)


def halt(msg: str) -> None:
    print(f"[ab_runner][ERROR] {msg}", file=sys.stderr)
    raise SystemExit(2)


def put_bytes(url: str, data: bytes) -> None:
    req = urllib.request.Request(url, data=data,
                                 headers={"Content-Type": "application/octet-stream"},
                                 method="PUT")
    with urllib.request.urlopen(req, timeout=180) as r:
        if not 200 <= r.status < 300:
            halt(f"upload PUT failed: {r.status}")


# --------------------------------------------------------------------------- helpers
def submit_package(agent: str, display_name: str, set_default: bool) -> dict:
    if not os.path.isfile(agent):
        halt(f"package not found: {agent}")
    data = open(agent, "rb").read()
    size, sha = len(data), hashlib.sha256(data).hexdigest()
    fname = os.path.basename(agent)
    if not fname.endswith(".agent"):
        fname += ".agent"
    tok = token()
    up = api("POST", CODES_API + "/codes/upload-url", {"filename": fname, "size": size}, tok)["data"]
    put_bytes(up["upload_url"], data)
    res = api("POST", CODES_API + "/codes", {
        "code_file_key": up["file_key"],
        "file_size": size,
        "sha256": sha,
        "display_name": display_name,
        "set_default": set_default,
    }, tok)
    out = {"agent": agent, "size": size, "sha256": sha,
           "display_name": display_name, "set_default": set_default,
           "result": res.get("data")}
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return out


def create_challenge(opponent: str) -> dict:
    body = {
        "opponent_player_id": opponent,
        "idempotency_key": str(uuid.uuid4()),
        "expected_cost_display": COST_DISPLAY,
    }
    return api("POST", "/arenas/3v3/challenges", body).get("data") or {}


def poll_match(match_uuid: str, timeout_min: float) -> dict:
    deadline = time.time() + timeout_min * 60
    last = None
    while time.time() < deadline:
        d = api("GET", f"/matches/{match_uuid}").get("data") or {}
        state = d.get("state")
        if state != last:
            print(f"[ab_runner] {match_uuid[:8]} state={state} "
                  f"score={d.get('home_score')}:{d.get('away_score')}", flush=True)
            last = state
        if state == "finished":
            return d
        time.sleep(20)
    halt(f"match {match_uuid} not finished within {timeout_min} min")


def run_cmd(cmd: list[str], dry: bool) -> None:
    print("[ab_runner] $ " + " ".join(cmd), flush=True)
    if dry:
        return
    subprocess.run(cmd, cwd=REPO, check=False)


def short(uuid_str: str) -> str:
    return uuid_str[:8]


# --------------------------------------------------------------------------- commands
def cmd_plan(_args) -> int:
    steps = [
        ("A", OPP_0707), ("B", OPP_0707), ("A", OPP_ZHANG), ("B", OPP_ZHANG),
    ]
    print("A/B 计划（4 场 = 40 credits，串行执行；arm A=v4.5b 控制，arm B=v5.0-final2 实验）\n")
    total = 0
    for i, (arm, opp) in enumerate(steps, 1):
        label, pkg, name = ARMS[arm]
        rel = os.path.relpath(pkg, REPO)
        print(f"# 第 {i} 场  arm={arm}({label})  对手={OPP_NAMES.get(opp, opp)}  ({opp})")
        print(f"python3 tools/ab_runner.py set_default {rel} --display-name {name}")
        print(f"python3 tools/ab_runner.py match {opp} --tag m{i}-{arm}-{OPP_NAMES.get(opp, 'opp')} --yes")
        total += 10
        print()
    print(f"预期消耗: {total} credits（4 x 10，注意每场需 default 已切到对应 arm；"
          f"submit/set_default 本身 0 credit）")
    print("invalid 场（平台冻结/对方 park）由 ab_runner 标记，手动补跑同 arm 同对手，不自动追加。")
    return 0


def cmd_submit(args) -> int:
    submit_package(args.agent, args.display_name, set_default=not args.no_default)
    return 0


def cmd_set_default(args) -> int:
    submit_package(args.agent, args.display_name, set_default=True)
    return 0


def cmd_match(args) -> int:
    opponent = args.opponent
    tag = args.tag or f"ab-{opponent[:8]}"
    dry = not args.yes
    print(f"[ab_runner] opponent={OPP_NAMES.get(opponent, opponent)} ({opponent}) tag={tag}")
    if dry:
        print(f"[ab_runner][DRY-RUN] 将向 POST {API}/arenas/3v3/challenges 发送：")
        print(json.dumps({
            "opponent_player_id": opponent,
            "idempotency_key": "<uuid4>",
            "expected_cost_display": COST_DISPLAY,
        }, ensure_ascii=False, indent=2))
        print(f"[ab_runner][DRY-RUN] 预估扣费 10 credits；加 --yes 才会真正发起挑战。")
        return 0

    res = create_challenge(opponent)
    match_uuid = res.get("match_uuid") or res.get("matchUuid")
    if not match_uuid:
        halt(f"challenge response missing match_uuid: {json.dumps(res)[:400]}")
    print(f"[ab_runner] challenge created: match_uuid={match_uuid} (cost={COST_DISPLAY})")
    rec = os.path.join("/tmp/ra/ab", "matches.jsonl")
    os.makedirs(os.path.dirname(rec), exist_ok=True)
    with open(rec, "a") as f:
        f.write(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                            "match_uuid": match_uuid, "opponent": opponent,
                            "tag": tag}, ensure_ascii=False) + "\n")
    detail = poll_match(match_uuid, args.timeout_min)
    hs, as_ = detail.get("home_score"), detail.get("away_score")
    print(f"[ab_runner] FINISHED {match_uuid} score {hs}:{as_}")

    # 归档（下载 manifest + segments），失败不阻塞判读输出
    run_cmd(["python3", "tools/online_match_fetch.py", match_uuid], dry=False)

    manifest = os.path.join(ARCHIVE_DIR, f"{match_uuid}-manifest.json")
    if not os.path.isfile(manifest):
        print("[ab_runner][WARN] manifest 未归档（fetch 失败或回放未就绪）→ 该场按 invalid/待查处理，"
              "请稍后手动重试 fetch，不要重复下单。")
        return 0

    if os.path.isfile(AB_ROW):
        run_cmd(["python3", AB_ROW, match_uuid], dry=False)
    if os.path.isfile(AB_VALID):
        print("[ab_runner] validity check:")
        subprocess.run(["python3", AB_VALID, match_uuid], cwd=REPO, check=False)
        out = subprocess.run(["python3", AB_VALID, match_uuid], cwd=REPO,
                             capture_output=True, text=True, check=False).stdout
        if "INVALID" in out.upper():
            print("[ab_runner][WARN] 该场判 INVALID（platform_freeze / opponent_park 等）→ "
                  "需手动补跑：同 arm、同对手、同 package；本工具不会自动追加（避免多花钱）。")
    print(f"[ab_runner] 记忆：把 uuid={match_uuid}、tag={tag}、对手={opponent} 报 analyst，"
          f"并补 records/online-loop。")
    return 0


def try_api(method: str, path: str, payload: dict | None = None,
            tok: str | None = None):
    """Like api() but returns None instead of halting (for optional endpoints)."""
    try:
        return api(method, path, payload, tok)
    except SystemExit:
        return None


def cmd_status(_args) -> int:
    tok = token()
    me = try_api("GET", "/player/me", tok)
    if me is not None:
        d = me.get("data") or {}
        print(json.dumps({"player": d.get("name"), "rating": d.get("rating"),
                          "credits": d.get("credits")}, ensure_ascii=False))
    arena = try_api("GET", "/arenas/3v3", tok)
    if arena is not None:
        a = arena.get("data") or {}
        print(json.dumps({"arena_cost": a.get("cost_display"),
                          "discount_cost": a.get("discount_cost_display")},
                         ensure_ascii=False))
    # 在线代码列表 + 当前默认（v4.5b=ver48 / v5 候选=ver49 …）
    lst = try_api("GET", CODES_API + "/codes", tok)
    if lst is not None:
        items = (lst.get("data") or {}).get("items") or []
        brief = [{"version": it.get("version"), "display_name": it.get("display_name"),
                  "is_default": it.get("is_default"), "id": it.get("id"),
                  "sha256": (it.get("sha256") or "")[:12]}
                 for it in items[:10]]
        print(json.dumps({"codes": brief}, ensure_ascii=False, indent=2))
    dflt = try_api("GET", CODES_API + "/codes/default", tok)
    if dflt is not None:
        d = dflt.get("data") or {}
        print(json.dumps({"default_code": {"version": d.get("version"),
                                           "display_name": d.get("display_name"),
                                           "id": d.get("id")}}, ensure_ascii=False))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("plan", help="print the full A/B sequence")
    p.set_defaults(fn=cmd_plan)

    for name, fn in (("submit", cmd_submit), ("set_default", cmd_set_default)):
        p = sub.add_parser(name, help=f"{name} a package")
        p.add_argument("agent")
        p.add_argument("--display-name", required=True)
        if name == "submit":
            p.add_argument("--no-default", action="store_true",
                           help="do NOT make it the default competition code")
        p.set_defaults(fn=fn)

    p = sub.add_parser("match", help="challenge one opponent (dry-run unless --yes)")
    p.add_argument("opponent")
    p.add_argument("--tag", default=None)
    p.add_argument("--yes", action="store_true", help="actually spend 10 credits")
    p.add_argument("--timeout-min", type=float, default=25.0)
    p.set_defaults(fn=cmd_match)

    p = sub.add_parser("status", help="credits / default code (best effort)")
    p.set_defaults(fn=cmd_status)

    args = ap.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
