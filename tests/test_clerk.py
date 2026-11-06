"""ward-clerk: the announcements it makes, and its loop against a real sim with a fake Switch."""
import json
import socket
import threading
import time
import urllib.request

import pytest
import uvicorn

from homeward import clerk, scenario
from homeward.sim.app import app


@pytest.fixture(scope="module")
def sim():
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


def call(base, method, path, body=None):
    req = urllib.request.Request(base + path, method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"content-type": "application/json"})
    with urllib.request.urlopen(req) as r:
        return json.loads(r.read() or b"{}")


def test_whole_day_announcements(sim, monkeypatch, capsys):
    monkeypatch.setattr(scenario, "BASE", sim)
    assert scenario.main(["margaret", "--auto"]) == 0
    ledger = call(sim, "GET", "/patients/12/ledger")
    plan = call(sim, "GET", "/patients/12/plan")
    said = [clerk.announce(e, plan) for e in ledger]
    msgs = [m for m in said if m]
    ward = [t for r, t in msgs if r == "ward"]
    bed = [t for r, t in msgs if r == "bed"]
    assert ward[0].startswith("@lead EPR update: Dr Raj has declared Margaret Jones (bed 12) medically fit")
    assert ward[-1] == "Margaret Jones left the ward at 12:40. Bed 12 is free."
    assert any(t.startswith("@transport Heads up: the transport provider cancelled Margaret's pickup (vehicle breakdown)")
               for t in bed)
    assert "Pharmacy: Margaret's discharge medicines are ready for collection on the ward (11:45)." in bed
    assert "EPR: Dr Raj signed Margaret's discharge letter at 11:00." in bed
    # agents and nurses speak for themselves: none of their entries is re-announced
    for e, m in zip(ledger, said):
        if e["actor"]["type"] == "agent" or (e["actor"]["type"] == "human" and e["approval_id"]):
            assert m is None


def test_crew_left_and_nudges_and_escalation():
    plan = {"bed": 12, "name": "Margaret Jones", "tasks": [
        {"id": "t1", "kind": "tto_verify", "label": "TTO verification"},
        {"id": "t4", "kind": "transport_booked", "label": "transport booking"}]}
    sys_actor = {"id": "engine", "role": "bed_manager", "type": "system"}
    crew = {"id": "ambulance-crew", "role": "transport", "type": "human"}
    r, t = clerk.announce({"action": "task.blocked", "task_id": "t4", "actor": crew, "at": "2026-11-07T12:15:00+00:00",
                           "detail": "crew arrived but patient not ready; crew left"}, plan)
    assert r == "bed" and t.startswith("@transport The crew arrived for bed 12 at 12:15 but Margaret wasn't ready")
    r, t = clerk.announce({"action": "nudge", "task_id": "t1", "actor": sys_actor, "at": "x",
                           "detail": "nudge 1 to pharmacist: TTO verification over target (60 min)"}, plan)
    assert t == "@meds Reminder for bed 12: TTO verification for Margaret is past its 60-minute target."
    r, t = clerk.announce({"action": "escalation", "task_id": "t4", "actor": sys_actor, "at": "x",
                           "detail": "escalated to bed_manager: transport booking 62 min since ready (target 30)"}, plan)
    assert t.startswith("@lead Escalation for bed 12: escalated to bed_manager")


def test_resolve_room():
    rooms = [{"room_id": "r1", "name": "SwitchAi: ward-7"}, {"room_id": "r2", "name": "SwitchAi: discharge-bed-12"}]
    assert clerk.resolve_room(rooms, "#ward-7") == "r1"
    assert clerk.resolve_room(rooms, "discharge-bed-12") == "r2"
    assert clerk.resolve_room(rooms, "pharmacy") is None


def test_run_loop_posts_only_new_hospital_events(sim, monkeypatch):
    monkeypatch.setattr(clerk, "SIM", sim)
    call(sim, "POST", "/reset", {"scenario": "margaret"})
    posts = []
    script = iter([
        lambda: call(sim, "POST", "/patients/12/mffd", {"pathway": "P0", "actor": {"id": "dr-raj", "role": "doctor"}}),
        lambda: call(sim, "POST", "/patients/12/tto/request",
                     {"actor": {"id": "pharmacy-liaison", "role": "coordinator", "type": "agent"}}),
        lambda: call(sim, "POST", "/clock", {"now": "2026-11-07T11:45:00+00:00"}),
    ])

    def fake_sleep(_):
        step = next(script, None)
        if step:
            step()

    assert clerk.run(["--interval", "0"], post=lambda room, text: posts.append((room, text)),
                     max_cycles=4, sleep=fake_sleep) == 0
    rooms = [r for r, _ in posts]
    assert rooms[0] == "ward" and posts[0][1].startswith("@lead EPR update")
    assert ("bed", "Pharmacy: Margaret's discharge medicines are ready for collection on the ward (11:45).") in posts
    assert not any("pharmacy-liaison" in t for _, t in posts)   # the agent's own request isn't echoed


def test_run_survives_sim_reset(sim, monkeypatch):
    monkeypatch.setattr(clerk, "SIM", sim)
    call(sim, "POST", "/reset", {"scenario": "margaret"})
    call(sim, "POST", "/patients/12/mffd", {"pathway": "P0", "actor": {"id": "dr-raj", "role": "doctor"}})
    posts = []
    script = iter([
        lambda: call(sim, "POST", "/reset", {"scenario": "margaret"}),
        lambda: call(sim, "POST", "/patients/12/mffd", {"pathway": "P0", "actor": {"id": "dr-raj", "role": "doctor"}}),
    ])
    clerk.run(["--interval", "0"], post=lambda r, t: posts.append((r, t)), max_cycles=3,
              sleep=lambda _: (next(script, lambda: None))())
    assert len([p for p in posts if p[1].startswith("@lead EPR update")]) == 1


def test_list_rooms_unwraps_operation_result(monkeypatch):
    rooms = [{"room_id": "r2", "name": "SwitchAi: discharge-bed-12"}]
    monkeypatch.setattr(clerk, "http", lambda *a, **k: {"result": rooms})
    assert clerk.list_rooms({"switch_url": "x", "agent_id": "a", "api_key": "k"}) == rooms
