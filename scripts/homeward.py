#!/usr/bin/env python3
"""Cross-platform entrypoint: python scripts/homeward.py <setup|demo|scenario|test>.

TASK-001 stub: `test` is real; the others are placeholders owned by later tasks
(setup/demo: TASK-003/008, scenario: TASK-007). Stdlib only.
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OWNERS = {"setup": "TASK-003/008", "demo": "TASK-003/006", "scenario": "TASK-007"}


def main(argv: list[str]) -> int:
    if not argv or argv[0] not in {"setup", "demo", "scenario", "test"}:
        print(__doc__)
        return 2
    cmd = argv[0]
    if cmd == "test":
        return subprocess.call([sys.executable, "-m", "pytest", "-q", *argv[1:]], cwd=ROOT)
    print(f"`{cmd}` is not implemented yet (owner: {OWNERS[cmd]}).")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
