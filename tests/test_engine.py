from datetime import datetime, timedelta, timezone

import pytest

from homeward import contracts as c
from homeward import engine as e

T0 = datetime(2026, 11, 7, 10, 0, tzinfo=timezone.utc)  # Margaret declared fit at 10:00
S = c.TaskStatus

NURSE = c.Actor("nurse-amy", c.Role.NURSE)
DOCTOR = c.Actor("dr-raj", c.Role.DOCTOR)
PHARMACIST = c.Actor("ph-lee", c.Role.PHARMACIST)
BED_MGR = c.Actor("bm-kim", c.Role.BED_MANAGER)
AGENT_LEAD = c.Actor("discharge-lead", c.Role.COORDINATOR, c.ActorType.AGENT)
AGENT_TRANSPORT = c.Actor("transport", c.Role.TRANSPORT, c.ActorType.AGENT)


def at(minutes):
    return T0 + timedelta(minutes=minutes)


def margaret(pathway=c.Pathway.P1):
    return e.build_plan(12, "Margaret Jones", pathway, T0)


def tid(p, kind):
    return e.find_task(p, kind).id


# --- build_plan ---------------------------------------------------------------
def test_plan_sizes_per_pathway():
    assert len(margaret(c.Pathway.P0).tasks) == 6
    assert len(margaret(c.Pathway.P1).tasks) == 9


def test_plan_initial_statuses_and_flags():
    p = margaret()
    dispense = e.find_task(p, c.TaskKind.TTO_DISPENSE)
    verify = e.find_task(p, c.TaskKind.TTO_VERIFY)
    letter = e.find_task(p, c.TaskKind.LETTER_SIGNED)
    assert verify.status == S.READY and verify.ready_at == T0 and verify.target_minutes == 60
    assert dispense.status == S.PENDING and dispense.depends_on == [verify.id] and dispense.ready_at is None
    assert letter.human_only and letter.owner_role == c.Role.DOCTOR
    assert [t.id for t in p.tasks] == [f"t{i}" for i in range(1, 10)]


# --- transitions --------------------------------------------------------------
def test_valid_transition_records_ledger():
    p = margaret()
    entries = e.apply_transition(p, tid(p, c.TaskKind.TTO_VERIFY), S.IN_PROGRESS, PHARMACIST, at(5), eta=at(40))
    t = e.find_task(p, c.TaskKind.TTO_VERIFY)
    assert t.status == S.IN_PROGRESS and t.eta == at(40)
    assert entries[0].action == "task.in_progress" and entries[0].actor == PHARMACIST and entries[0].at == at(5)


def test_invalid_transition_rejected_and_state_unchanged():
    p = margaret()
    d = tid(p, c.TaskKind.TTO_DISPENSE)
    with pytest.raises(c.HomewardError) as ex:
        e.apply_transition(p, d, S.DONE, PHARMACIST, at(1))
    assert ex.value.code == c.ErrorCode.INVALID_TRANSITION
    assert e.get_task(p, d).status == S.PENDING


def test_done_is_terminal():
    p = margaret()
    v = tid(p, c.TaskKind.TTO_VERIFY)
    e.apply_transition(p, v, S.DONE, PHARMACIST, at(30))
    with pytest.raises(c.HomewardError) as ex:
        e.apply_transition(p, v, S.READY, PHARMACIST, at(31))
    assert ex.value.code == c.ErrorCode.INVALID_TRANSITION


def test_completing_dependency_promotes_dependant():
    p = margaret()
    entries = e.apply_transition(p, tid(p, c.TaskKind.TTO_VERIFY), S.DONE, PHARMACIST, at(40))
    dispense = e.find_task(p, c.TaskKind.TTO_DISPENSE)
    assert dispense.status == S.READY and dispense.ready_at == at(40)
    assert [x.action for x in entries] == ["task.done", "task.ready"]
    assert entries[1].actor.type == c.ActorType.SYSTEM


def test_unknown_task_is_not_found():
    with pytest.raises(c.HomewardError) as ex:
        e.apply_transition(margaret(), "t99", S.DONE, NURSE, at(1))
    assert ex.value.code == c.ErrorCode.NOT_FOUND


# --- non-clinical and approval guarantees --------------------------------------
def test_agent_cannot_sign_letter():
    p = margaret()
    with pytest.raises(c.HomewardError) as ex:
        e.apply_transition(p, tid(p, c.TaskKind.LETTER_SIGNED), S.DONE, AGENT_LEAD, at(10))
    assert ex.value.code == c.ErrorCode.HUMAN_ONLY
    assert e.find_task(p, c.TaskKind.LETTER_SIGNED).status == S.READY


def test_nurse_cannot_sign_letter_but_doctor_can():
    p = margaret()
    letter = tid(p, c.TaskKind.LETTER_SIGNED)
    with pytest.raises(c.HomewardError) as ex:
        e.apply_transition(p, letter, S.DONE, NURSE, at(10))
    assert ex.value.code == c.ErrorCode.HUMAN_ONLY
    e.apply_transition(p, letter, S.DONE, DOCTOR, at(10))
    assert e.get_task(p, letter).status == S.DONE


def test_awaiting_approval_needs_a_human():
    p = margaret()
    tr = tid(p, c.TaskKind.TRANSPORT_BOOKED)
    e.apply_transition(p, tr, S.AWAITING_APPROVAL, AGENT_TRANSPORT, at(20), approval_id="A-1")
    with pytest.raises(c.HomewardError) as ex:
        e.apply_transition(p, tr, S.DONE, AGENT_TRANSPORT, at(21), approval_id="A-1")
    assert ex.value.code == c.ErrorCode.APPROVAL_REQUIRED
    with pytest.raises(c.HomewardError) as ex2:
        e.apply_transition(p, tr, S.IN_PROGRESS, AGENT_TRANSPORT, at(21), approval_id="A-1")
    assert ex2.value.code == c.ErrorCode.APPROVAL_REQUIRED
    entries = e.apply_transition(p, tr, S.IN_PROGRESS, NURSE, at(22), approval_id="A-1")
    assert entries[0].approval_id == "A-1" and entries[0].actor == NURSE
    assert e.get_task(p, tr).status == S.IN_PROGRESS


def test_agent_can_complete_non_clinical_task():
    p = margaret()
    e.apply_transition(p, tid(p, c.TaskKind.FAMILY_INFORMED), S.DONE, AGENT_LEAD, at(15))
    assert e.find_task(p, c.TaskKind.FAMILY_INFORMED).status == S.DONE


def test_wrong_human_role_forbidden():
    p = margaret()
    with pytest.raises(c.HomewardError) as ex:
        e.apply_transition(p, tid(p, c.TaskKind.TTO_VERIFY), S.DONE, BED_MGR, at(5))
    assert ex.value.code == c.ErrorCode.FORBIDDEN_ROLE


def test_nurse_may_complete_non_clinical_tasks_of_other_roles():
    p = margaret()
    e.apply_transition(p, tid(p, c.TaskKind.TTO_VERIFY), S.DONE, NURSE, at(5))
    assert e.find_task(p, c.TaskKind.TTO_VERIFY).status == S.DONE


# --- pickup rule ---------------------------------------------------------------
def test_pickup_exactly_at_buffer_passes():
    assert e.check_pickup(at(125), tto_eta=at(105), letter_eta=at(60)) == at(125)


def test_pickup_one_minute_early_fails():
    with pytest.raises(c.HomewardError) as ex:
        e.check_pickup(at(124), tto_eta=at(105), letter_eta=at(60))
    assert ex.value.code == c.ErrorCode.PICKUP_TOO_EARLY
    assert ex.value.details["earliest"] == at(125).isoformat()


def test_pickup_uses_later_of_the_two_etas():
    with pytest.raises(c.HomewardError):
        e.check_pickup(at(125), tto_eta=at(60), letter_eta=at(110))


def test_pickup_needs_some_eta():
    with pytest.raises(c.HomewardError) as ex:
        e.check_pickup(at(125), None, None)
    assert ex.value.code == c.ErrorCode.VALIDATION


# --- blocker ---------------------------------------------------------------------
def test_blocker_unknown_eta_counts_as_latest():
    p = margaret(c.Pathway.P0)
    for kind in (c.TaskKind.TTO_VERIFY, c.TaskKind.LETTER_SIGNED, c.TaskKind.TRANSPORT_BOOKED,
                 c.TaskKind.FAMILY_INFORMED, c.TaskKind.BELONGINGS):
        e.find_task(p, kind).eta = at(30)
    b = e.blocker(p, at(1))
    assert b.task_id == tid(p, c.TaskKind.TTO_DISPENSE)  # pending, no ETA
    assert b.summary.startswith("Margaret is waiting on: TTO dispensing (ETA unknown). Owner: pharmacist.")


def test_blocker_picks_latest_eta():
    p = margaret(c.Pathway.P0)
    for t in p.tasks:
        t.eta = at(30)
    e.find_task(p, c.TaskKind.TTO_DISPENSE).eta = at(105)
    b = e.blocker(p, at(1))
    assert b.task_id == tid(p, c.TaskKind.TTO_DISPENSE) and b.eta == at(105)
    assert "(ETA 11:45)" in b.summary


def test_blocked_task_wins():
    p = margaret()
    tr = tid(p, c.TaskKind.TRANSPORT_BOOKED)
    e.apply_transition(p, tr, S.BLOCKED, c.Actor("sim", c.Role.TRANSPORT, c.ActorType.SYSTEM), at(80),
                       detail="transport_cancelled")
    b = e.blocker(p, at(80))
    assert b.task_id == tr and "BLOCKED: transport booking" in b.summary


def test_blocker_when_all_done_and_after_departure():
    p = margaret(c.Pathway.P0)
    e.apply_transition(p, tid(p, c.TaskKind.TTO_VERIFY), S.DONE, PHARMACIST, at(40))
    finish = [k for k in c.PATHWAY_TASKS[c.Pathway.P0] if k != c.TaskKind.TTO_VERIFY]
    for k in finish:
        t = e.find_task(p, k)
        e.apply_transition(p, t.id, S.DONE, c.Actor("h", t.owner_role), at(150))
    assert "ready to go home" in e.blocker(p, at(151)).summary
    e.depart(p, NURSE, at(160))
    assert e.blocker(p, at(161)).summary == "Margaret went home at 12:40."


# --- nudges / escalation -------------------------------------------------------
def test_nudge_nudge_escalate_exactly_once():
    p = margaret()
    v = tid(p, c.TaskKind.TTO_VERIFY)  # target 60 min, ready at T0

    def mine(entries):
        return [x for x in entries if x.task_id == v]

    assert mine(e.tick(p, at(59))) == []
    n1 = mine(e.tick(p, at(60)))
    assert [x.action for x in n1] == ["nudge"]
    assert mine(e.tick(p, at(60))) == []          # idempotent
    assert [x.action for x in mine(e.tick(p, at(90)))] == ["nudge"]
    esc = mine(e.tick(p, at(120)))
    assert [x.action for x in esc] == ["escalation"] and "bed_manager" in esc[0].detail
    assert mine(e.tick(p, at(500))) == []


def test_tick_catches_up_in_one_call():
    p = margaret()
    actions = [x.action for x in e.tick(p, at(200)) if x.task_id == tid(p, c.TaskKind.TTO_VERIFY)]
    assert actions == ["nudge", "nudge", "escalation"]


def test_rebook_restarts_clock():
    p = margaret()
    tr = tid(p, c.TaskKind.TRANSPORT_BOOKED)  # target 30
    e.tick(p, at(30))
    assert e.find_task(p, c.TaskKind.TRANSPORT_BOOKED).nudges == 1
    sim = c.Actor("sim", c.Role.TRANSPORT, c.ActorType.SYSTEM)
    e.apply_transition(p, tr, S.BLOCKED, sim, at(80))
    e.apply_transition(p, tr, S.READY, AGENT_TRANSPORT, at(81))
    t = e.get_task(p, tr)
    assert t.nudges == 0 and t.ready_at == at(81)
    assert [x for x in e.tick(p, at(100)) if x.task_id == tr] == []


def test_done_tasks_are_not_nudged():
    p = margaret()
    e.apply_transition(p, tid(p, c.TaskKind.TTO_VERIFY), S.DONE, PHARMACIST, at(30))
    assert all(x.task_id != tid(p, c.TaskKind.TTO_VERIFY) for x in e.tick(p, at(300)))


def test_overdue_lists_tasks_past_target():
    p = margaret()
    assert e.overdue(p, at(29)) == []
    assert e.overdue(p, at(30)) == [tid(p, c.TaskKind.TRANSPORT_BOOKED)]


# --- cost and departure ----------------------------------------------------------
def test_cost_at_known_times():
    p = margaret()
    assert e.cost(p, T0) == {"hours": 0.0, "gbp": 0.0}
    assert e.cost(p, at(390)) == {"hours": 6.5, "gbp": round(6.5 * c.BED_HOUR_GBP, 2)}


def test_cost_stops_at_departure():
    p = margaret(c.Pathway.P0)
    e.apply_transition(p, tid(p, c.TaskKind.TTO_VERIFY), S.DONE, PHARMACIST, at(30))
    finish_all_rest = [k for k in c.PATHWAY_TASKS[c.Pathway.P0] if k != c.TaskKind.TTO_VERIFY]
    for k in finish_all_rest:
        t = e.find_task(p, k)
        e.apply_transition(p, t.id, S.DONE, c.Actor("h", t.owner_role), at(150))
    e.depart(p, NURSE, at(160))
    assert e.cost(p, at(600)) == e.cost(p, at(160))


def test_departure_blocked_until_all_done():
    p = margaret()
    with pytest.raises(c.HomewardError) as ex:
        e.depart(p, NURSE, at(10))
    assert ex.value.code == c.ErrorCode.DEPENDENCY_UNMET and len(ex.value.details["open"]) == 9


def test_agent_cannot_confirm_departure():
    with pytest.raises(c.HomewardError) as ex:
        e.depart(margaret(), AGENT_LEAD, at(10))
    assert ex.value.code == c.ErrorCode.APPROVAL_REQUIRED


def test_no_changes_after_departure():
    p = margaret(c.Pathway.P0)
    e.apply_transition(p, tid(p, c.TaskKind.TTO_VERIFY), S.DONE, PHARMACIST, at(30))
    for k in [k for k in c.PATHWAY_TASKS[c.Pathway.P0] if k != c.TaskKind.TTO_VERIFY]:
        t = e.find_task(p, k)
        e.apply_transition(p, t.id, S.DONE, c.Actor("h", t.owner_role), at(150))
    e.depart(p, NURSE, at(160))
    with pytest.raises(c.HomewardError):
        e.apply_transition(p, "t1", S.READY, NURSE, at(170))
    assert e.tick(p, at(999)) == []


# --- handover ------------------------------------------------------------------
def test_handover_summary_contents():
    p = margaret()
    e.apply_transition(p, tid(p, c.TaskKind.TTO_VERIFY), S.IN_PROGRESS, PHARMACIST, at(20), eta=at(40))
    text = e.handover_summary(p, at(120))
    assert text.startswith("Bed 12 Margaret Jones (P1), medically fit since 10:00 (2.0 bed-hours")
    assert "discharge letter signature: ready, owner doctor" in text and "[clinical, human only]" in text
    assert "Next deadline: transport booking by 10:30." in text
    assert "Done: 0/9 tasks." in text


def test_transport_target_met_once_approved():
    p = margaret()
    tr = tid(p, c.TaskKind.TRANSPORT_BOOKED)
    e.apply_transition(p, tr, S.AWAITING_APPROVAL, AGENT_TRANSPORT, at(10), approval_id="A-1")
    e.apply_transition(p, tr, S.IN_PROGRESS, NURSE, at(12), approval_id="A-1", eta=at(135))
    assert tr not in e.overdue(p, at(200))
    assert [x for x in e.tick(p, at(200)) if x.task_id == tr] == []


def test_tto_clock_keeps_running_while_in_progress():
    p = margaret()
    v = tid(p, c.TaskKind.TTO_VERIFY)
    e.apply_transition(p, v, S.IN_PROGRESS, PHARMACIST, at(5), eta=at(45))
    assert v in e.overdue(p, at(60))
