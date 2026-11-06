"""End-to-end: run the real CLI as a subprocess against a real uvicorn server, as agents do."""
import json
import os
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
import uvicorn

from homeward.sim.app import app

ROOT = Path(__file__).resolve().parent.parent
CLI = [sys.executable, str(ROOT / "scripts" / "homeward.py")]
AGENT = {"id": "pharmacy-liaison", "role": "pharmacist", "type": "agent"}


@pytest.fixture(scope="module")
def server():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    th = threading.Thread(target=srv.run, daemon=True)
    th.start()
    for _ in range(100):
        if srv.started:
            break
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}"
    srv.should_exit = True
    th.join(timeout=5)


def run(url, *args, stdin=None):
    env = {**os.environ, "HOMEWARD_URL": url}
    p = subprocess.run([*CLI, *args], capture_output=True, text=True, encoding="utf-8", env=env, input=stdin)
    return p.returncode, p.stdout


@pytest.fixture
def fresh(server):
    assert run(server, "write", "POST", "/reset", '{"scenario":"margaret"}')[0] == 0
    return server


def last_json(out):
    return json.loads(out.strip().splitlines()[-1])


def test_read_health(fresh):
    code, out = run(fresh, "read", "/health")
    assert code == 0 and last_json(out)["now"] == "2026-11-07T10:00:00+00:00"


def test_read_blocker_leads_with_summary_line(fresh):
    run(fresh, "write", "POST", "/patients/12/mffd", '{"pathway":"P0","actor":{"id":"dr-raj","role":"doctor"}}')
    code, out = run(fresh, "read", "/patients/12/blocker")
    first = out.splitlines()[0]
    assert code == 0 and first.startswith("Margaret is waiting on:") and "bed-hours, £" in first


def test_read_handover_is_plain_text(fresh):
    run(fresh, "write", "POST", "/patients/12/mffd", '{"pathway":"P1","actor":{"id":"dr-raj","role":"doctor"}}')
    code, out = run(fresh, "read", "/patients/12/handover")
    assert code == 0 and out.startswith("Bed 12 Margaret Jones (P1)")


def test_write_rejection_exit_1_with_reason(fresh):
    run(fresh, "write", "POST", "/patients/12/mffd", '{"pathway":"P0","actor":{"id":"dr-raj","role":"doctor"}}')
    body = json.dumps({"status": "done", "actor": {"id": "discharge-lead", "role": "coordinator", "type": "agent"}})
    code, out = run(fresh, "write", "PATCH", "/patients/12/tasks/t3", body)
    assert code == 1 and out.startswith("REJECTED HUMAN_ONLY:")
    assert last_json(out)["error"]["code"] == "HUMAN_ONLY"


def test_write_from_stdin_and_booking_summary(fresh):
    run(fresh, "write", "POST", "/patients/12/mffd", '{"pathway":"P0","actor":{"id":"dr-raj","role":"doctor"}}')
    run(fresh, "write", "POST", "/patients/12/tto/request", "-", stdin=json.dumps({"actor": AGENT}))
    body = {"slot": "2026-11-07T12:15:00+00:00", "actor": {"id": "transport", "role": "transport", "type": "agent"}}
    code, out = run(fresh, "write", "POST", "/patients/12/transport/bookings", json.dumps(body))
    assert code == 0 and out.startswith("Booking B-") and "waiting for nurse approval (approval_id A-" in out


def test_usage_errors_exit_2(fresh):
    assert run(fresh, "read")[0] == 2
    assert run(fresh, "read", "http://evil.example/x")[0] == 2
    assert run(fresh, "write", "GET", "/health")[0] == 2          # reads are not writes
    assert run(fresh, "write", "DELETE", "/patients/12")[0] == 2
    assert run(fresh, "write", "POST", "/reset", "{not json")[0] == 2


def test_sim_down_exit_3():
    code, out = run("http://127.0.0.1:9", "read", "/health")
    assert code == 3 and "not reachable" in out


def test_paths_without_slash_and_git_bash_rewrite(fresh):
    assert run(fresh, "read", "health")[0] == 0
    assert run(fresh, "read", "C:/Program Files/Git/patients/12")[0] == 0
    assert run(fresh, "read", "C:/Users/x/secrets.txt")[0] == 2   # not an API path
    assert run(fresh, "read", "etc/passwd")[0] == 2
