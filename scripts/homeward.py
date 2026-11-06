#!/usr/bin/env python3
"""Homeward entrypoint (cross-platform; stdlib only).

  python scripts/homeward.py setup              create .venv and install requirements.txt
  python scripts/homeward.py test [pytest args] run the test suite
  python scripts/homeward.py demo [--port N]    start the simulator + board on http://127.0.0.1:8765
  python scripts/homeward.py scenario <name>    run a scripted scenario (P6)

Agent tools (talk to the running sim; base URL from HOMEWARD_URL, default http://127.0.0.1:8765):
  python scripts/homeward.py read <path>                   GET only, e.g. read /patients/12/blocker
  python scripts/homeward.py write <POST|PATCH> <path> '<json>'   changes state; needs human approval in Switch
      e.g. write POST /patients/12/tto/request '{"actor":{"id":"pharmacy-liaison","role":"pharmacist","type":"agent"}}'
      Use '-' as the JSON to read it from stdin.
  Exit codes: 0 ok, 1 rejected by Homeward (error JSON printed), 2 usage, 3 sim not reachable.

`make <cmd>` is a thin wrapper for Mac/Linux.
"""
import json
import os
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
    print("`scenario` is not implemented yet (P6).")
    return 1


def base_url() -> str:
    return os.environ.get("HOMEWARD_URL", f"http://127.0.0.1:{PORT}").rstrip("/")


def http(method: str, path: str, body=None):
    """Return (status, parsed_body). Raises ConnectionError if the sim is down."""
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


def _check_path(path: str) -> bool:
    return path.startswith("/") and "://" not in path


def cmd_read(args):
    if len(args) != 1 or not _check_path(args[0]):
        print("usage: homeward.py read <path>   (path starts with /, e.g. /patients/12/blocker)")
        return 2
    try:
        status, out = http("GET", args[0])
    except ConnectionError as ex:
        print(f"Homeward sim not reachable at {base_url()} ({ex}). Start it: python scripts/homeward.py demo")
        return 3
    return emit(args[0], status, out)


def cmd_write(args):
    if len(args) not in (2, 3) or args[0].upper() not in WRITE_METHODS or not _check_path(args[1]):
        print("usage: homeward.py write <POST|PATCH> <path> ['<json>' | -]")
        return 2
    method, path = args[0].upper(), args[1]
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
