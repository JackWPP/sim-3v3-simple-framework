"""Send a command to the Studio renderer bridge and print the JSON result.

Usage:
    python3 tools/bcmd.py booster.agent.getProjectInfo
    python3 tools/bcmd.py --wait 240 booster.agent.build '{"workspacePath": "/x"}'

Requires the polling loop installed in Studio's DevTools console
(see tools/studio_bridge_install.txt).
"""
import json, sys, time, urllib.request

BASE = "http://127.0.0.1:8765"


def post(path, obj):
    req = urllib.request.Request(BASE + path, data=json.dumps(obj).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def get(path, timeout=40):
    with urllib.request.urlopen(BASE + path, timeout=timeout) as r:
        return json.loads(r.read())


def run(cmd, args, wait):
    rid = post("/cmd", {"cmd": cmd, "args": args})["id"]
    deadline = time.time() + wait
    while True:
        try:
            res = get(f"/result?id={rid}")
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


def _truncate(obj, limit=2000):
    """Trim very long strings (e.g. agentIconData base64) so output stays readable."""
    if isinstance(obj, str):
        if len(obj) <= limit:
            return obj
        return obj[:limit] + f"...<truncated {len(obj) - limit} chars>"
    if isinstance(obj, list):
        return [_truncate(v, limit) for v in obj]
    if isinstance(obj, dict):
        return {k: _truncate(v, limit) for k, v in obj.items()}
    return obj


if __name__ == "__main__":
    argv = sys.argv[1:]
    wait = 30.0
    if argv and argv[0] == "--wait":
        wait = float(argv[1]); argv = argv[2:]
    if not argv:
        print("usage: bcmd.py [--wait SEC] <command> [json-args]"); sys.exit(1)
    cmd = argv[0]
    args = json.loads(argv[1]) if len(argv) > 1 else None
    print(json.dumps(_truncate(run(cmd, args, wait)), ensure_ascii=False))
