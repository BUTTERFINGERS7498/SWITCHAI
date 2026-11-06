"""The full demo day in --auto mode, against a real server on a private port."""
import socket
import threading
import time

import pytest
import uvicorn

from homeward import scenario
from homeward.sim.app import app


@pytest.fixture(scope="module")
def base():
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


def test_margaret_auto_goes_home_at_1240(base, monkeypatch, capsys):
    monkeypatch.setattr(scenario, "BASE", base)
    assert scenario.main(["margaret", "--auto"]) == 0
    out = capsys.readouterr().out
    assert "Curveball: the transport provider cancels the 12:15 pickup" in out
    assert "Margaret went home at 12:40 instead of 19:10." in out
    assert "freed vs baseline: 6.5 h" in out
    assert "Human approvals: 2 (nurse-amy)" in out and "clinical actions by agents: 0" in out


def test_unknown_scenario(base, monkeypatch):
    monkeypatch.setattr(scenario, "BASE", base)
    assert scenario.main(["nope"]) == 2


def test_sim_down(monkeypatch):
    monkeypatch.setattr(scenario, "BASE", "http://127.0.0.1:9")
    assert scenario.main(["margaret", "--auto"]) == 3
