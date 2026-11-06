#!/usr/bin/env python3
"""Homeward entrypoint (cross-platform; stdlib only).

  python scripts/homeward.py setup              create .venv and install requirements.txt
  python scripts/homeward.py test [pytest args] run the test suite
  python scripts/homeward.py demo [--port N]    start the simulator + board on http://127.0.0.1:8765
  python scripts/homeward.py scenario <name>    run a scripted scenario (P6)

`make <cmd>` is a thin wrapper for Mac/Linux.
"""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VENV = ROOT / ".venv"
PORT = int(os.environ.get("HOMEWARD_PORT", "8765"))


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


COMMANDS = {"setup": cmd_setup, "test": cmd_test, "demo": cmd_demo, "scenario": cmd_scenario}


def main(argv):
    if not argv or argv[0] not in COMMANDS:
        print(__doc__)
        return 2
    return COMMANDS[argv[0]](argv[1:])


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
