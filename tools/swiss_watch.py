"""S2 SWISS official-stage watcher: poll next match, archive it, append one log line.

Official S2 SWISS stage (11-29 23:59 → 12-01 23:59, 15 rounds) does NOT consume
arena credits. This tool is read-only against the platform; it never creates
challenges.

Usage:
  # 常驻轮询（每 60s 检查一次；SWISS 阶段出现 next-match 时自动等待/归档/记一行）
  python3 tools/swiss_watch.py [--interval 60] [--expect-sha e7dcc0d6]

  # 单次检查（cron / 手动）
  python3 tools/swiss_watch.py --once

  # 干跑：用已归档的 finished match 演练「归档 → 分析 → 追加一行」逻辑，
  # 不轮询线上、不碰真实 swiss-log（写到 --out 指定的临时文件）
  python3 tools/swiss_watch.py --dry-run --match-uuid 0ab411d9-ac45-4fd8-b40f-2383d1d0c54c

实现约束（Lead round 4）：
- 所有读接口走 `node /tmp/cdp.js api GET <path>` 页面上下文，避免 token 过期；
  需要 sha256 的默认代码信息用 `node /tmp/cdp.js eval` 在页面内 fetch（codes 列表
  响应较长，cdp api 会截断 4000 字符）。
- 匹配 finished 后：tools/online_match_fetch.py 归档 → tools/online_replay_analyze.py
  → /tmp/ra/ab_row.py → 追加 docs/kb/online-matches/swiss-log.md。
- --expect-sha <sha8>：默认代码 sha 前缀不符只告警、不拦截。
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time

API = "/api/v1/competition"
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ARCHIVE = os.path.join(REPO, "docs", "kb", "online-matches")
SWISS_LOG = os.path.join(ARCHIVE, "swiss-log.md")
STATE_FILE = "/tmp/swiss_watch_state.json"
AB_ROW = "/tmp/ra/ab_row.py"
FETCH = os.path.join(REPO, "tools", "online_match_fetch.py")
ANALYZE = os.path.join(REPO, "tools", "online_replay_analyze.py")

HEADER = (
    "| 时间 | 对手 | 版本 sha | 比分 | 我方罚单 | shots | 射正 | 球半场% |\n"
    "|---|---|---|---|---|---|---|---|\n"
)


def log(msg: str) -> None:
    print(f"[swiss_watch {time.strftime('%H:%M:%S')}] {msg}", flush=True)


# ------------------------------------------------------------------ CDP page calls
def cdp_api_get(path: str) -> dict | None:
    """GET via page context. Returns parsed inner JSON body (or None on failure)."""
    try:
        p = subprocess.run(
            ["node", "/tmp/cdp.js", "api", "GET", path],
            capture_output=True, text=True, timeout=90,
        )
        outer = json.loads(p.stdout.strip())
        body = json.loads(outer["body"])
        if outer.get("status") != 200:
            log(f"WARN {path} status={outer.get('status')} body={str(body)[:200]}")
        return body
    except Exception as exc:  # noqa: BLE001 - 页面/网络异常都应降级为 None
        log(f"WARN cdp_api_get {path} failed: {exc}")
        return None


def cdp_eval_json(js: str):
    """Evaluate JS in page context and parse its (stringified) JSON return value."""
    try:
        p = subprocess.run(
            ["node", "/tmp/cdp.js", "eval", js],
            capture_output=True, text=True, timeout=90,
        )
        out = p.stdout.strip()
        val = json.loads(out)
        if isinstance(val, str):
            val = json.loads(val)
        return val
    except Exception as exc:  # noqa: BLE001
        log(f"WARN cdp_eval failed: {exc}")
        return None


def default_code_info() -> dict | None:
    """{'v': version, 'n': display_name, 's': sha256} of the default code (via page)."""
    js = (
        "(async()=>{const t=localStorage.getItem('booster_auth_token');"
        "const r=await fetch('https://api.booster.tech/api/v1/competition/3v3/codes',"
        "{headers:{Authorization:'Bearer '+t}});"
        "const j=await r.json();"
        "const d=(j.data.items||[]).filter(x=>x.is_default)"
        ".map(x=>({v:x.version,n:x.display_name,s:x.sha256||null}));"
        "return JSON.stringify(d);})()"
    )
    d = cdp_eval_json(js)
    if isinstance(d, list) and d:
        return d[0]
    # 降级：/codes/default 只有 version/display_name
    body = cdp_api_get(API + "/3v3/codes/default")
    data = (body or {}).get("data")
    if isinstance(data, dict):
        return {"v": data.get("version"), "n": data.get("display_name"), "s": None}
    return None


def season_overview() -> dict | None:
    body = cdp_api_get(API + "/seasons/s2/overview")
    return (body or {}).get("data")


def next_match() -> dict | None:
    body = cdp_api_get(API + "/seasons/s2/teams/me/next-match")
    return (body or {}).get("data")


def match_detail(match_uuid: str) -> dict | None:
    body = cdp_api_get(API + "/matches/" + match_uuid)
    return (body or {}).get("data")


# ------------------------------------------------------------------ match handling
def field(d: dict, *keys):
    for k in keys:
        if d.get(k) not in (None, "", []):
            return d[k]
    return None


def match_uuid_of(d: dict) -> str | None:
    v = field(d, "match_uuid", "matchUuid", "uuid", "id")
    return str(v) if v else None


def opponent_of(d: dict) -> str:
    for key in ("opponent_name", "opponentName", "opponent"):
        v = d.get(key)
        if isinstance(v, str) and v:
            return v
        if isinstance(v, dict):
            nm = field(v, "name", "team_name", "display_name", "teamName")
            if nm:
                return str(nm)
    for key in ("home_team", "away_team", "opponent_team", "team"):
        v = d.get(key)
        if isinstance(v, dict):
            nm = field(v, "name", "team_name", "display_name", "teamName")
            if nm:
                return str(nm)
    pid = field(d, "opponent_player_id", "opponentPlayerId")
    return str(pid) if pid else "?"


def start_time_of(d: dict) -> str:
    v = field(d, "scheduled_at", "scheduledAt", "start_at", "startAt",
              "start_time", "match_time", "created_at")
    return str(v) if v else ""


def wait_finished(match_uuid: str, interval: float = 20.0,
                  timeout_min: float = 30.0) -> dict | None:
    deadline = time.time() + timeout_min * 60
    last = None
    while time.time() < deadline:
        d = match_detail(match_uuid)
        if d:
            state = d.get("state")
            if state != last:
                score = f"{d.get('home_score')}:{d.get('away_score')}"
                log(f"match {match_uuid[:8]} state={state} score={score}")
                last = state
            if state == "finished":
                return d
        time.sleep(interval)
    log(f"WARN match {match_uuid[:8]} 未在 {timeout_min} 分钟内 finished")
    return None


def ensure_archive(match_uuid: str) -> str | None:
    manifest = os.path.join(ARCHIVE, f"{match_uuid}-manifest.json")
    if os.path.isfile(manifest):
        return manifest
    log(f"归档 {match_uuid[:8]}（online_match_fetch.py）...")
    p = subprocess.run(["python3", FETCH, match_uuid], cwd=REPO,
                       capture_output=True, text=True, timeout=900)
    if p.returncode != 0:
        log(f"WARN fetch 失败: {p.stderr[-300:]}")
    return manifest if os.path.isfile(manifest) else None


def ensure_analysis(match_uuid: str, manifest: str) -> str | None:
    out = os.path.join(ARCHIVE, f"{match_uuid}-analysis.txt")
    if os.path.isfile(out) and os.path.getsize(out) > 0:
        return out
    log(f"分析 {match_uuid[:8]}（online_replay_analyze.py）...")
    seg = os.path.join(ARCHIVE, f"{match_uuid}-segments")
    with open(out, "w") as f:
        p = subprocess.run(["python3", ANALYZE, manifest, "--segments", seg],
                           cwd=REPO, stdout=f, stderr=subprocess.PIPE,
                           text=True, timeout=900)
    if p.returncode != 0:
        log(f"WARN analyze 失败: {(p.stderr or '')[-300:]}")
        return None
    return out


def ab_row(match_uuid: str) -> dict:
    """Run /tmp/ra/ab_row.py and parse its markdown row into cells."""
    res = {"ok": False}
    if not os.path.isfile(AB_ROW):
        log("WARN /tmp/ra/ab_row.py 不存在，跳过指标行")
        return res
    p = subprocess.run(["python3", AB_ROW, match_uuid], cwd=REPO,
                       capture_output=True, text=True, timeout=600)
    for line in (p.stdout or "").splitlines():
        if line.startswith("| ") and match_uuid[:8] in line:
            cells = [c.strip() for c in line.split("|")]
            # ['', uuid, opp(score), shots, on, goals, box, ballH%, possH%, oobCaused,
            #  penalties, goals_detail, '']
            if len(cells) >= 12:
                res.update({
                    "ok": True, "opp_score": cells[2], "shots": cells[3],
                    "on": cells[4], "goals": cells[5], "box": cells[6],
                    "ball_h": cells[7], "penalties": cells[10],
                })
    return res


def our_penalties(pen_cell: str, focus_home: bool) -> tuple[str, int]:
    """penalties cell 形如 'H:illegalPosition,defender_set_play_interference / A:-'."""
    ours, theirs = "", ""
    try:
        parts = pen_cell.split("/")
        for part in parts:
            part = part.strip()
            if part.startswith("H:"):
                ours = part[2:].strip()
            elif part.startswith("A:"):
                theirs = part[2:].strip()
    except Exception:  # noqa: BLE001
        pass
    side = ours if focus_home else theirs
    if not side or side in ("-", "无"):
        return "0", 0
    rules = [x.strip() for x in side.split(",") if x.strip()]
    return f"{len(rules)} ({', '.join(rules)})", len(rules)


def manifest_fallback(match_uuid: str) -> dict:
    """ab_row 失败时的兜底：从 manifest events 解析比分/我方罚单（shots/球半场仍为 ?）。"""
    out = {"ok": False}
    man_path = os.path.join(ARCHIVE, f"{match_uuid}-manifest.json")
    try:
        with open(man_path) as f:
            man = json.load(f)
    except Exception:  # noqa: BLE001
        return out
    teams = (man.get("match") or {}).get("teams") or {}
    home_name = str((teams.get("home") or {}).get("teamName") or "")
    focus_home = "Robot" in home_name
    pen = {"home": [], "away": []}
    for e in man.get("events", []):
        if e.get("type") != "penalty":
            continue
        side = (e.get("actor") or {}).get("side")
        rid = ((e.get("evidence") or {}).get("ruleId")
               or (e.get("outcome") or {}).get("reason") or "?")
        if side in pen:
            pen[side].append(str(rid))
    ours = pen["home"] if focus_home else pen["away"]
    theirs = pen["away"] if focus_home else pen["home"]
    fmt = lambda xs: ",".join(xs) if xs else "-"  # noqa: E731
    out.update({"ok": True, "penalties": f"H:{fmt(pen['home'])} / A:{fmt(pen['away'])}",
                "shots": "?", "on": "?", "ball_h": "?", "focus_home": focus_home,
                "our_pen": len(ours), "their_pen": len(theirs)})
    return out


def build_row(match_uuid: str, detail: dict, code: dict | None,
              row: dict, finished_at: str) -> str:
    teams = detail.get("home_team") or {}
    home_name = (teams.get("name") if isinstance(teams, dict) else None) or ""
    focus_home = home_name != "" and "Robot" in str(home_name)
    # 若 detail 没给 home_team 名，退回 ab_row 的 opp(score) 判断
    if not home_name:
        focus_home = True
    pen_txt, _ = our_penalties(row.get("penalties", ""), focus_home)
    sha8 = (code or {}).get("s", "")[:8] if (code or {}).get("s") else ""
    ver = (code or {}).get("v")
    ver_txt = f"ver{ver}" if ver else "?"
    code_txt = sha8 if sha8 else ver_txt
    score = row.get("opp_score") or (
        f"{detail.get('home_score')}:{detail.get('away_score')}")
    # ab_row 的 opp(score) cell 形如 "如果以后 5:0"，只取比分部分
    if isinstance(score, str) and " " in score:
        score = score.rsplit(" ", 1)[-1]
    return (f"| {finished_at or start_time_of(detail)} | {row.get('opp_name') or ''} "
            f"| {code_txt} | {score} | {pen_txt} | {row.get('shots', '?')} "
            f"| {row.get('on', '?')} | {row.get('ball_h', '?')} |")


def append_row(path: str, row: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if not os.path.isfile(path) or os.path.getsize(path) == 0:
        with open(path, "w") as f:
            f.write("# S2 SWISS 官方赛记录\n\n" + HEADER)
    with open(path, "a") as f:
        f.write(row + "\n")
    log(f"已追加 → {os.path.abspath(path)}")


def run_match_pipeline(match_uuid: str, code: dict | None,
                       out_path: str = SWISS_LOG) -> bool:
    detail = match_detail(match_uuid) or {}
    finished = field(detail, "finished_at", "finishedAt") or time.strftime("%Y-%m-%d %H:%M")
    manifest = ensure_archive(match_uuid)
    if manifest:
        ensure_analysis(match_uuid, manifest)
    row = ab_row(match_uuid)
    if not row.get("ok"):
        fb = manifest_fallback(match_uuid)
        if fb.get("ok"):
            log("WARN ab_row 指标缺失，用 manifest 兜底（比分/罚单可用，shots 列记 ?）")
            row.update({"shots": "?", "on": "?", "ball_h": "?",
                        "penalties": fb["penalties"]})
        else:
            log("WARN ab_row 指标缺失，仍以 detail 兜底记一行")
            row.update({"shots": "?", "on": "?", "ball_h": "?", "penalties": ""})
    # 对手名：优先 detail 的非本队 side
    teams = detail.get("home_team") or {}
    home_name = str(teams.get("name") if isinstance(teams, dict) else "") or ""
    if "Robot" in home_name:
        away = detail.get("away_team") or {}
        row["opp_name"] = (away.get("name") if isinstance(away, dict) else "") or "?"
    else:
        row["opp_name"] = home_name or "?"
    line = build_row(match_uuid, detail, code, row, finished)
    append_row(out_path, line)
    print(line)
    return True


# ------------------------------------------------------------------ state / main
def load_state() -> dict:
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except Exception:  # noqa: BLE001
        return {"processed": []}


def save_state(st: dict) -> None:
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(st, f)
    except Exception:  # noqa: BLE001
        pass


def check_expect_sha(code: dict | None, expect: str | None) -> None:
    if not expect:
        return
    sha = (code or {}).get("s") or ""
    exp = expect.lower()
    if sha.lower().startswith(exp):
        log(f"default code sha OK ({sha[:8]} == {exp})")
    else:
        log(f"WARN default code sha 不符：当前 {sha[:8] or '?'} vs 期望 {exp}"
            f"（仅告警，不拦截）")


def find_latest_archived_match() -> str | None:
    files = []
    try:
        for name in os.listdir(ARCHIVE):
            if name.endswith("-manifest.json"):
                files.append((os.path.getmtime(os.path.join(ARCHIVE, name)),
                              name[: -len("-manifest.json")]))
    except FileNotFoundError:
        return None
    return sorted(files)[-1][1] if files else None


def rehearse(match_uuid: str, code: dict | None, out_path: str) -> int:
    log(f"[dry-run] 用已 finished 场次 {match_uuid[:8]} 演练归档/分析/追加逻辑")
    detail = match_detail(match_uuid) or {}
    log(f"[dry-run] state={detail.get('state')} "
        f"score={detail.get('home_score')}:{detail.get('away_score')}")
    if detail.get("state") != "finished":
        log("WARN dry-run 建议使用已 finished 的 match")
    run_match_pipeline(match_uuid, code, out_path=out_path)
    log(f"[dry-run] 未轮询线上、未创建挑战；结果写入 {out_path}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--interval", type=float, default=60.0,
                    help="轮询间隔秒（默认 60）")
    ap.add_argument("--once", action="store_true", help="只做一次检查后退出")
    ap.add_argument("--dry-run", action="store_true",
                    help="用已归档 finished match 演练，不轮询线上")
    ap.add_argument("--match-uuid", default=None,
                    help="--dry-run 时指定演练用 match；缺省取最新归档")
    ap.add_argument("--expect-sha", default=None,
                    help="期望的默认代码 sha 前缀（不符仅告警）")
    ap.add_argument("--out", default=None,
                    help="日志输出路径（默认 docs/kb/online-matches/swiss-log.md；dry-run 默认 /tmp/swiss_dryrun_log.md）")
    args = ap.parse_args()

    code = default_code_info()
    if code:
        log(f"default code: ver{code.get('v')} {code.get('n')} "
            f"sha={(code.get('s') or '?')[:8]}")
    check_expect_sha(code, args.expect_sha)

    if args.dry_run:
        uuid = args.match_uuid or find_latest_archived_match()
        if not uuid:
            log("ERROR 没有可演练的已归档 match")
            return 2
        out = args.out or "/tmp/swiss_dryrun_log.md"
        return rehearse(uuid, code, out)

    out = args.out or SWISS_LOG
    st = load_state()
    processed = set(st.get("processed", []))
    while True:
        ov = season_overview()
        phase = (ov or {}).get("current_phase")
        log(f"current_phase={phase} ({(ov or {}).get('current_phase_name', '')})")
        handled = False
        if phase == "SWISS":
            nm = next_match()
            if not nm:
                log("SWISS 阶段：next-match = null（暂无待打场次）")
            else:
                muuid = match_uuid_of(nm)
                if not muuid:
                    log(f"WARN next-match 无法解析 match_uuid：{json.dumps(nm)[:300]}")
                elif muuid in processed:
                    log(f"match {muuid[:8]} 已处理过，跳过")
                else:
                    log(f"发现待打比赛 {muuid[:8]} 对手={opponent_of(nm)} "
                        f"开赛={start_time_of(nm)}")
                    detail = wait_finished(muuid)
                    if detail:
                        run_match_pipeline(muuid, default_code_info() or code, out)
                        processed.add(muuid)
                        st["processed"] = sorted(processed)
                        save_state(st)
                        handled = True
                    else:
                        log("WARN 本场未能确认 finished；下一轮继续观察（不重复下单）")
        if args.once:
            log("--once：单次检查结束")
            return 0
        time.sleep(max(20.0, args.interval))


if __name__ == "__main__":
    raise SystemExit(main())
