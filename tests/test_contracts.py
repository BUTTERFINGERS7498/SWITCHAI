from datetime import datetime, timezone

from homeward import contracts as c


def test_every_status_has_transition_entry():
    assert set(c.TRANSITIONS) == set(c.TaskStatus)


def test_terminal_states_have_no_exits():
    assert c.TRANSITIONS[c.TaskStatus.DONE] == frozenset()
    assert c.TRANSITIONS[c.TaskStatus.CANCELLED] == frozenset()
    assert not c.can_transition(c.TaskStatus.DONE, c.TaskStatus.READY)


def test_pending_cannot_jump_to_done():
    assert not c.can_transition(c.TaskStatus.PENDING, c.TaskStatus.DONE)


def test_blocked_can_recover_to_ready():
    assert c.can_transition(c.TaskStatus.BLOCKED, c.TaskStatus.READY)


def test_letter_is_human_only():
    assert c.is_human_only(c.TaskKind.LETTER_SIGNED)
    assert not c.is_human_only(c.TaskKind.TRANSPORT_BOOKED)


def test_all_kinds_have_owner_and_deps():
    for k in c.TaskKind:
        assert k in c.OWNER_ROLE and k in c.DEPENDS_ON


def test_pathway_templates():
    assert len(c.PATHWAY_TASKS[c.Pathway.P0]) == 6
    assert c.TaskKind.HANDOVER_PACK_SENT in c.PATHWAY_TASKS[c.Pathway.P1]
    assert c.TaskKind.HANDOVER_PACK_SENT not in c.PATHWAY_TASKS[c.Pathway.P0]
    for p, kinds in c.PATHWAY_TASKS.items():
        for k in kinds:
            assert all(d in kinds for d in c.DEPENDS_ON[k]), (p, k)


def test_error_wire_shape():
    e = c.HomewardError(c.ErrorCode.HUMAN_ONLY, "agents cannot sign letters", {"task": "t3"})
    assert e.to_wire() == {"error": {"code": "HUMAN_ONLY", "message": "agents cannot sign letters",
                                     "details": {"task": "t3"}}}


def test_to_wire_is_json_safe():
    import json
    t = datetime(2026, 11, 7, 10, 0, tzinfo=timezone.utc)
    p = c.Patient(12, "Margaret Jones", c.Pathway.P1, t)
    out = c.to_wire(p)
    json.dumps(out)
    assert out["pathway"] == "P1" and out["fit_at"].startswith("2026-11-07T10:00")
