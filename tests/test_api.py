import pytest
from fastapi.testclient import TestClient

from homeward.sim.app import app

DOCTOR = {"id": "dr-raj", "role": "doctor"}
NURSE = {"id": "nurse-amy", "role": "nurse"}
LEAD = {"id": "discharge-lead", "role": "coordinator", "type": "agent"}
PHARM_AGENT = {"id": "pharmacy-liaison", "role": "pharmacist", "type": "agent"}
TRANSPORT = {"id": "transport", "role": "transport", "type": "agent"}
DAY = "2026-11-07T"


@pytest.fixture
def api():
    c = TestClient(app)
    assert c.post("/reset", json={"scenario": "margaret"}).status_code == 200
    return c


def t(hhmm):
    return f"{DAY}{hhmm}:00+00:00"


def clock(api, hhmm):
    r = api.post("/clock", json={"now": t(hhmm)})
    assert r.status_code == 200, r.text
    return r.json()


def task_id(api, bed, kind):
    return next(x["id"] for x in api.get(f"/patients/{bed}/plan").json()["tasks"] if x["kind"] == kind)


def task(api, bed, kind):
    return next(x for x in api.get(f"/patients/{bed}/plan").json()["tasks"] if x["kind"] == kind)


def err(r, status, code):
    assert r.status_code == status, r.text
    assert r.json()["error"]["code"] == code
    return r.json()["error"]


def mffd(api, bed=12, pathway="P0"):
    r = api.post(f"/patients/{bed}/mffd", json={"pathway": pathway, "actor": DOCTOR})
    assert r.status_code == 200, r.text
    return r.json()


# --- basics ----------------------------------------------------------------------------
def test_health_and_reset(api):
    h = api.get("/health").json()
    assert h["ok"] and h["now"] == t("10:00") and h["contract"] == "1.2.0"
    clock(api, "11:00")
    assert api.post("/reset", json={}).json()["now"] == t("10:00")


def test_seeded_ward(api):
    beds = {p["bed"]: p for p in api.get("/patients").json()}
    assert set(beds) == {3, 7, 12, 15}
    assert not beds[12]["declared_fit"]
    assert beds[3]["blocker"].startswith("Arthur is waiting on: transport booking")
    assert "BLOCKED: care package start" in beds[7]["blocker"]


def test_clock_only_moves_forward_and_validates(api):
    err(api.post("/clock", json={"now": t("09:00")}), 422, "VALIDATION")
    err(api.post("/clock", json={}), 422, "VALIDATION")
    assert api.post("/clock", json={"advance_minutes": 15}).json()["now"] == t("10:15")


def test_unknown_bed_and_unfit_bed(api):
    err(api.get("/patients/99"), 404, "NOT_FOUND")
    err(api.get("/patients/12/plan"), 404, "NOT_FOUND")


def test_bad_body_uses_contract_error_shape(api):
    e = err(api.post("/patients/12/mffd", json={"pathway": "P9", "actor": DOCTOR}), 422, "VALIDATION")
    assert e["details"]["errors"]


# --- MFFD and non-clinical guarantees ------------------------------------------------------
def test_only_doctor_declares_mffd(api):
    err(api.post("/patients/12/mffd", json={"pathway": "P1", "actor": LEAD}), 403, "HUMAN_ONLY")
    plan = mffd(api, pathway="P1")
    assert len(plan["tasks"]) == 9 and plan["fit_at"] == t("10:00")
    err(api.post("/patients/12/mffd", json={"pathway": "P1", "actor": DOCTOR}), 422, "VALIDATION")


def test_agent_cannot_sign_letter_over_http(api):
    mffd(api)
    letter = task_id(api, 12, "letter_signed")
    err(api.patch(f"/patients/12/tasks/{letter}", json={"status": "done", "actor": LEAD}), 403, "HUMAN_ONLY")
    assert task(api, 12, "letter_signed")["status"] == "ready"


def test_agent_cannot_fake_pharmacy_status(api):
    mffd(api)
    v = task_id(api, 12, "tto_verify")
    err(api.patch(f"/patients/12/tasks/{v}", json={"status": "done", "actor": PHARM_AGENT}), 403, "FORBIDDEN_ROLE")


def test_agent_cannot_mark_transport_done_directly(api):
    mffd(api)
    tr = task_id(api, 12, "transport_booked")
    err(api.patch(f"/patients/12/tasks/{tr}", json={"status": "done", "actor": TRANSPORT}), 409, "APPROVAL_REQUIRED")


# --- pharmacy ----------------------------------------------------------------------------
def test_tto_request_runs_on_the_clock(api):
    mffd(api)
    r = api.post("/patients/12/tto/request", json={"actor": PHARM_AGENT, "priority": "urgent"})
    assert r.json()["status"] == "verifying" and r.json()["ready_eta"] == t("11:45")
    err(api.post("/patients/12/tto/request", json={"actor": PHARM_AGENT}), 422, "VALIDATION")
    clock(api, "11:00")
    assert task(api, 12, "tto_verify")["status"] == "done"
    assert task(api, 12, "tto_dispense")["status"] == "in_progress"
    clock(api, "11:45")
    assert api.get("/patients/12/tto").json()["status"] == "ready"
    assert task(api, 12, "tto_dispense")["status"] == "done"


def test_tto_delay_event_moves_eta(api):
    mffd(api)
    api.post("/patients/12/tto/request", json={"actor": PHARM_AGENT})
    api.post("/events", json={"type": "tto_delayed", "bed": 12, "minutes": 30})
    assert api.get("/patients/12/tto").json()["ready_eta"] == t("12:15")
    clock(api, "10:50")
    assert task(api, 12, "tto_verify")["status"] == "in_progress"  # old 10:50 event superseded
    clock(api, "11:20")
    assert task(api, 12, "tto_verify")["status"] == "done"


# --- transport -------------------------------------------------------------------------------
def test_eligibility_and_slots(api):
    mffd(api)
    el = api.get("/patients/12/transport/eligibility").json()
    assert el["vehicle"] == "wheelchair" and el["earliest_pickup"] == t("11:20")  # letter 11:00 + 20
    slots = api.get("/transport/slots", params={"vehicle": "wheelchair"}).json()["slots"]
    assert slots[0] == t("11:00") and len(slots) == 12
    err(api.get("/transport/slots", params={"vehicle": "rocket"}), 422, "VALIDATION")


def test_booking_rules(api):
    mffd(api)
    api.post("/patients/12/tto/request", json={"actor": PHARM_AGENT})
    err(api.post("/patients/12/transport/bookings", json={"slot": t("12:00"), "actor": TRANSPORT}),
        409, "PICKUP_TOO_EARLY")
    err(api.post("/patients/12/transport/bookings", json={"slot": t("12:15"), "actor": TRANSPORT, "vehicle": "car"}),
        422, "VALIDATION")
    err(api.post("/patients/12/transport/bookings", json={"slot": t("12:20"), "actor": TRANSPORT}),
        422, "VALIDATION")  # not on a 15-minute boundary
    b = api.post("/patients/12/transport/bookings", json={"slot": t("12:15"), "actor": TRANSPORT}).json()
    assert b["status"] == "pending_approval" and b["approval_id"].startswith("A-")
    assert task(api, 12, "transport_booked")["status"] == "awaiting_approval"
    err(api.post("/patients/12/transport/bookings", json={"slot": t("12:30"), "actor": TRANSPORT}),
        422, "VALIDATION")  # one active booking per bed
    # agents and non-nurses cannot approve
    url = f"/patients/12/transport/bookings/{b['id']}/confirm"
    err(api.post(url, json={"approval_id": b["approval_id"], "approver": TRANSPORT}), 409, "APPROVAL_REQUIRED")
    err(api.post(url, json={"approval_id": b["approval_id"], "approver": DOCTOR}), 409, "APPROVAL_REQUIRED")
    err(api.post(url, json={"approval_id": "A-999", "approver": NURSE}), 422, "VALIDATION")
    ok = api.post(url, json={"approval_id": b["approval_id"], "approver": NURSE}).json()
    assert ok["status"] == "confirmed" and ok["approved_by"] == "nurse-amy"
    assert task(api, 12, "transport_booked")["status"] == "in_progress"


def test_decline_frees_the_slot(api):
    mffd(api)
    api.post("/patients/12/tto/request", json={"actor": PHARM_AGENT})
    b = api.post("/patients/12/transport/bookings", json={"slot": t("12:15"), "actor": TRANSPORT}).json()
    d = api.post(f"/patients/12/transport/bookings/{b['id']}/decline", json={"approver": NURSE}).json()
    assert d["status"] == "declined" and task(api, 12, "transport_booked")["status"] == "ready"
    assert t("12:15") in api.get("/transport/slots", params={"vehicle": "wheelchair"}).json()["slots"]


def test_crew_leaves_if_patient_not_ready(api):
    mffd(api)
    api.post("/patients/12/tto/request", json={"actor": PHARM_AGENT})
    b = api.post("/patients/12/transport/bookings", json={"slot": t("12:15"), "actor": TRANSPORT}).json()
    api.post(f"/patients/12/transport/bookings/{b['id']}/confirm",
             json={"approval_id": b["approval_id"], "approver": NURSE})
    clock(api, "12:15")  # letter never signed, family not told
    assert task(api, 12, "transport_booked")["status"] == "blocked"
    assert "crew left" in api.get("/patients/12/blocker").json()["summary"] or \
        "BLOCKED" in api.get("/patients/12/blocker").json()["summary"]


# --- the demo journey ---------------------------------------------------------------------
def test_margaret_full_journey_with_curveball(api):
    plan = mffd(api, pathway="P0")
    assert plan["tasks"][0]["kind"] == "tto_verify"
    b0 = api.get("/patients/12/blocker").json()
    assert b0["summary"].startswith("Margaret is waiting on:")

    api.post("/patients/12/tto/request", json={"actor": PHARM_AGENT})
    assert api.get("/patients/12/transport/eligibility").json()["earliest_pickup"] == t("12:05")

    clock(api, "10:25")
    b1 = api.post("/patients/12/transport/bookings", json={"slot": t("12:15"), "actor": TRANSPORT}).json()
    api.post(f"/patients/12/transport/bookings/{b1['id']}/confirm",
             json={"approval_id": b1["approval_id"], "approver": NURSE})

    for kind in ("family_informed", "belongings"):
        r = api.patch(f"/patients/12/tasks/{task_id(api, 12, kind)}", json={"status": "done", "actor": LEAD})
        assert r.status_code == 200, r.text

    clock(api, "11:00")
    api.post("/events", json={"type": "letter_signed", "bed": 12, "doctor": "dr-raj"})

    # curveball, scheduled in advance: provider cancels at 11:20
    assert api.post("/events", json={"type": "transport_cancelled", "bed": 12, "at": t("11:20"),
                                     "reason": "vehicle breakdown"}).json()["scheduled"]
    clock(api, "11:20")
    blk = api.get("/patients/12/blocker").json()
    assert "BLOCKED: transport booking" in blk["summary"]
    slots = api.get("/transport/slots", params={"vehicle": "wheelchair", "after": t("12:05")}).json()["slots"]
    assert slots[0] == t("12:30")  # 12:15 went with the cancelled vehicle

    b2 = api.post("/patients/12/transport/bookings", json={"slot": slots[0], "actor": TRANSPORT}).json()
    api.post(f"/patients/12/transport/bookings/{b2['id']}/confirm",
             json={"approval_id": b2["approval_id"], "approver": NURSE})

    clock(api, "12:40")
    p = api.get("/patients/12").json()
    assert p["departed_at"] == t("12:40")
    blk = api.get("/patients/12/blocker").json()
    assert blk["summary"] == "Margaret went home at 12:40."
    assert blk["cost"]["hours"] == pytest.approx(2.67, abs=0.01)

    actions = [x["action"] for x in api.get("/patients/12/ledger").json()]
    assert actions[0] == "patient.mffd" and actions[-1] == "patient.departed"
    approvals = [x for x in api.get("/patients/12/ledger").json() if x["approval_id"] and x["actor"]["type"] == "human"]
    assert [x["actor"]["id"] for x in approvals] == ["nurse-amy", "nurse-amy"]


def test_handover_and_board(api):
    mffd(api, pathway="P1")
    text = api.get("/patients/12/handover").text
    assert text.startswith("Bed 12 Margaret Jones (P1)") and "[clinical, human only]" in text
    board = api.get("/board/ward").json()
    assert board["now"] == t("10:00") and len(board["beds"]) == 4
    m = next(b for b in board["beds"] if b["bed"] == 12)
    assert m["blocker"].startswith("Margaret is waiting on:") and len(m["tasks"]) == 9
    assert board["totals"]["bed_hours"] > 0 and len(board["ledger"]) <= 12


def test_arthur_goes_home_on_his_own(api):
    clock(api, "11:10")
    assert api.get("/patients/3").json()["departed_at"] == t("11:10")


def test_escalation_shows_in_ledger(api):
    mffd(api)
    clock(api, "12:00")  # TTO never requested: verify target 60 -> nudges, escalate at 12:00
    actions = [x["action"] for x in api.get("/patients/12/ledger").json()]
    assert actions.count("nudge") >= 2 and "escalation" in actions


def test_agent_records_as_itself_with_attribution(api):
    mffd(api)
    t5 = task_id(api, 12, "family_informed")
    r = api.patch(f"/patients/12/tasks/{t5}", json={"status": "done", "actor": LEAD,
                                                    "detail": "reported by nurse-amy: daughter Sarah told at 10:05"})
    assert r.status_code == 200, r.text
    row = r.json()["ledger"][0]
    assert row["actor"] == {"id": "discharge-lead", "role": "coordinator", "type": "agent"}
    assert row["detail"] == "reported by nurse-amy: daughter Sarah told at 10:05"


def test_coordinator_agent_still_cannot_do_clinical_or_approve(api):
    mffd(api)
    err(api.patch(f"/patients/12/tasks/{task_id(api, 12, 'letter_signed')}",
                  json={"status": "done", "actor": LEAD}), 403, "HUMAN_ONLY")
    err(api.post("/patients/12/mffd", json={"pathway": "P0", "actor": LEAD}), 403, "HUMAN_ONLY")


def test_booking_with_approver_is_one_call(api):
    mffd(api)
    api.post("/patients/12/tto/request", json={"actor": PHARM_AGENT})
    b = api.post("/patients/12/transport/bookings",
                 json={"slot": t("12:15"), "actor": TRANSPORT, "approver": NURSE}).json()
    assert b["status"] == "confirmed" and b["approved_by"] == "nurse-amy"
    assert task(api, 12, "transport_booked")["status"] == "in_progress"
    actions = [x["action"] for x in api.get("/patients/12/ledger").json()]
    assert actions[-2:] == ["task.awaiting_approval", "task.in_progress"]


def test_booking_with_agent_as_approver_is_rolled_back(api):
    mffd(api)
    api.post("/patients/12/tto/request", json={"actor": PHARM_AGENT})
    err(api.post("/patients/12/transport/bookings",
                 json={"slot": t("12:15"), "actor": TRANSPORT, "approver": TRANSPORT}), 409, "APPROVAL_REQUIRED")
    assert task(api, 12, "transport_booked")["status"] == "ready"
    assert t("12:15") in api.get("/transport/slots", params={"vehicle": "wheelchair"}).json()["slots"]


def test_board_page_and_totals(api):
    r = api.get("/board")
    assert r.status_code == 200 and "text/html" in r.headers["content-type"]
    assert "Ward 7 · Homeward" in r.text and "textContent" in r.text and "innerHTML" not in r.text
    d = api.get("/board/ward").json()
    assert d["totals"]["approvals"] == 1  # Arthur's seeded booking, approved by nurse-amy
    m = next(b for b in d["beds"] if b["bed"] == 12)
    assert m["baseline_departure"] == t("19:10")


def test_board_people_totals(api):
    d = api.get("/board/ward").json()["totals"]
    assert d["ready"] == 2 and d["home"] == 0 and d["clinical_by_agents"] == 0 and d["hours_freed"] == 0
    clock(api, "11:10")
    assert api.get("/board/ward").json()["totals"]["home"] == 1   # Arthur
