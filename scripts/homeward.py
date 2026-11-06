#!/usr/bin/env python3
"""Homeward entrypoint (cross-platform; stdlib only).

  python scripts/homeward.py setup              create .venv and install requirements.txt
  python scripts/homeward.py test [pytest args] run the test suite
  python scripts/homeward.py demo [--port N]    start the simulator + board on http://127.0.0.1:8765
  python scripts/homeward.py scenario margaret [--auto]   run the demo day (needs `demo` running)

Agent tools (talk to the running sim; base URL from HOMEWARD_URL, default http://127.0.0.1:8765):
  python scripts/homeward.py read <path>                   GET only, e.g. read patients/12/blocker
  python scripts/homeward.py write <POST|PATCH> <path> '<json>'   changes state; needs human approval in Switch
      e.g. write POST patients/12/tto/request '{"actor":{"id":"pharmacy-liaison","role":"pharmacist","type":"agent"}}'
      Use '-' as the JSON to read it from stdin. Write paths without a leading '/' (Git Bash rewrites it).
  Exit codes: 0 ok, 1 rejected by Homeward (error JSON printed), 2 usage, 3 sim not reachable.

`make <cmd>` is a thin wrapper for Mac/Linux.
"""
import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENV = ROOT / ".venv"
PORT = int(os.environ.get("HOMEWARD_PORT", "8765"))
WRITE_METHODS = ("POST", "PATCH")


def venv_python() -> Path:
    return VENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def python_for_app() -> str:
    """Prefer the project venv; fall back to the current interpreter."""
    vp = venv_python()
    return str(vp) if vp.exists() else sys.executable


def cmd_setup(_args):
    if not venv_python().exists():
        print(f"creating {VENV}")
        subprocess.check_call([sys.executable, "-m", "venv", str(VENV)])
    vp = str(venv_python())
    subprocess.check_call([vp, "-m", "pip", "install", "-q", "--upgrade", "pip"])
    subprocess.check_call([vp, "-m", "pip", "install", "-q", "-r", str(ROOT / "requirements.txt")])
    print("setup done. Next: python scripts/homeward.py test && python scripts/homeward.py demo")
    return 0


def cmd_test(args):
    return subprocess.call([python_for_app(), "-m", "pytest", "-q", *args], cwd=ROOT)


def cmd_demo(args):
    port = PORT
    if "--port" in args:
        port = int(args[args.index("--port") + 1])
    print(f"Homeward sim on http://127.0.0.1:{port}  (API docs: /docs)")
    return subprocess.call([python_for_app(), "-m", "uvicorn", "homeward.sim.app:app",
                            "--host", "127.0.0.1", "--port", str(port)], cwd=ROOT)


def cmd_scenario(args):
    sys.path.insert(0, str(ROOT))
    from homeward import scenario
    return scenario.main(args)


def base_url() -> str:
    return os.environ.get("HOMEWARD_URL", f"http://127.0.0.1:{PORT}").rstrip("/")


def http(method: str, path: str, body=None):
    """Return (status, parsed_body). Raises ConnectionError if the sim is down."""
    if "?" in path:  # '+' in a query means space; keep timezone offsets like +00:00 intact
        base, query = path.split("?", 1)
        path = base + "?" + query.replace("+", "%2B")
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base_url() + path, data=data, method=method,
                                 headers={"content-type": "application/json", "accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            status, raw, ctype = r.status, r.read(), r.headers.get("content-type", "")
    except urllib.error.HTTPError as ex:
        status, raw, ctype = ex.code, ex.read(), ex.headers.get("content-type", "")
    except (urllib.error.URLError, OSError) as ex:
        raise ConnectionError(str(ex)) from ex
    text = raw.decode("utf-8", errors="replace")
    return status, (json.loads(text) if "json" in ctype and text else text)


def summarize(path: str, out) -> str:
    """One human line to lead the output, so chat replies stay short."""
    if isinstance(out, dict):
        if "error" in out:
            err = out["error"]
            return f"REJECTED {err.get('code')}: {err.get('message')}"
        if "summary" in out:
            cost = out.get("cost") or {}
            extra = f" | {cost.get('hours')} bed-hours, £{cost.get('gbp')}" if cost else ""
            return out["summary"] + extra
        if out.get("status") == "confirmed" and "slot" in out:
            return f"Booking {out['id']} confirmed: {out['vehicle']} pickup {out['slot'][11:16]}, approved by {out['approved_by']}."
        if out.get("status") == "pending_approval":
            return (f"Booking {out['id']} for {out['slot'][11:16]} is waiting for nurse approval "
                    f"(approval_id {out['approval_id']}).")
    return ""


def emit(path: str, status: int, out) -> int:
    line = summarize(path, out)
    if line:
        print(line)
    print(out if isinstance(out, str) else json.dumps(out, ensure_ascii=False, separators=(",", ":")))
    return 0 if status < 400 else 1


API_ROOTS = ("health", "reset", "clock", "patients", "transport", "board", "events")


def normalize_path(arg: str):
    """Return an API path like /patients/12, or None if invalid.
    Accepts 'patients/12' or '/patients/12'. Git Bash on Windows rewrites a leading '/' into a
    Windows path (e.g. 'C:/Program Files/Git/patients/12'); that rewrite is undone here."""
    if "://" in arg:
        return None
    a = arg.replace("\\", "/")
    if re.match(r"^[A-Za-z]:/", a):
        m = re.search(r"/(%s)(/|\?|$)" % "|".join(API_ROOTS), a)
        if not m:
            return None
        a = a[m.start():]
    if not a.startswith("/"):
        a = "/" + a
    root = a[1:].split("/", 1)[0].split("?", 1)[0]
    return a if root in API_ROOTS else None


def cmd_read(args):
    path = normalize_path(args[0]) if len(args) == 1 else None
    if not path:
        print("usage: homeward.py read <path>   e.g. read patients/12/blocker")
        return 2
    try:
        status, out = http("GET", path)
    except ConnectionError as ex:
        print(f"Homeward sim not reachable at {base_url()} ({ex}). Start it: python scripts/homeward.py demo")
        return 3
    return emit(path, status, out)


def cmd_write(args):
    path = normalize_path(args[1]) if len(args) in (2, 3) else None
    if not path or args[0].upper() not in WRITE_METHODS:
        print("usage: homeward.py write <POST|PATCH> <path> ['<json>' | -]   e.g. write POST patients/12/tto/request '{...}'")
        return 2
    method = args[0].upper()
    raw = args[2] if len(args) == 3 else "{}"
    if raw == "-":
        raw = sys.stdin.read()
    try:
        body = json.loads(raw)
    except json.JSONDecodeError as ex:
        print(f"body is not valid JSON: {ex}")
        return 2
    try:
        status, out = http(method, path, body)
    except ConnectionError as ex:
        print(f"Homeward sim not reachable at {base_url()} ({ex}). Start it: python scripts/homeward.py demo")
        return 3
    return emit(path, status, out)


COMMANDS = {"setup": cmd_setup, "test": cmd_test, "demo": cmd_demo, "scenario": cmd_scenario,
            "read": cmd_read, "write": cmd_write}


def main(argv):
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    if not argv or argv[0] not in COMMANDS:
        print(__doc__)
        return 2
    return COMMANDS[argv[0]](argv[1:])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
