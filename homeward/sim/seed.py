"""Synthetic ward 7 (all data invented). Built through the real Store operations, so the
seeded history is a valid ledger, then the clock is left at 10:00 for the demo.

Margaret Jones (bed 12) is the demo patient: not yet declared fit at 10:00.
With Homeward: TTO requested 10:20 -> verified 11:00 -> ready 11:45; letter due 11:00;
earliest pickup 12:05 -> slot 12:15; provider cancels at 11:20 -> rebook 12:30 -> leaves 12:40.
Without Homeward (dossier baseline) she left at 19:10.
"""
from __future__ import annotations

from datetime import datetime, timezone

from homeward.contracts import Actor, ActorType, Pathway, Role, TaskKind, TaskStatus
from homeward import engine as e
from homeward.sim.state import Inpatient, Store

DAY = datetime(2026, 11, 7, tzinfo=timezone.utc)
DEMO_START = DAY.replace(hour=10)
BASELINE_DEPARTURE = DAY.replace(hour=19, minute=10)

NURSE = Actor("nurse-amy", Role.NURSE, ActorType.HUMAN)
DOCTOR = Actor("dr-raj", Role.DOCTOR, ActorType.HUMAN)
SOCIAL = Actor("sw-ola", Role.SOCIAL_WORKER, ActorType.HUMAN)


def at(h: int, m: int = 0) -> datetime:
    return DAY.replace(hour=h, minute=m)


def ward7() -> Store:
    s = Store(at(8, 0))
    s.add_inpatient(Inpatient(3, "Arthur Bell", 77, "independent", next_of_kin="daughter"))
    s.add_inpatient(Inpatient(7, "Doris Patel", 88, "wheelchair", escort=True, next_of_kin="son"))
    s.add_inpatient(Inpatient(12, "Margaret Jones", 82, "wheelchair", next_of_kin="daughter Sarah"))
    s.add_inpatient(Inpatient(15, "Tom Hughes", 64, "independent", next_of_kin="wife"))

    # Doris (bed 7, P3 care home): fit 08:00, everything moving except the care-home bed.
    s.declare_mffd(7, Pathway.P3, DOCTOR, letter_eta=at(8, 45))
    s.advance_to(at(8, 30))
    s.request_tto(7, NURSE)
    s.apply_event("letter_signed", {"bed": 7, "doctor": "dr-raj"})
    p7 = s.plan(7)
    care = e.find_task(p7, TaskKind.CARE_START_CONFIRMED)
    s.update_task(7, care.id, TaskStatus.BLOCKED, SOCIAL)  # no care-home bed available yet

    # Arthur (bed 3, P0 home): fit 08:30, nearly done, car at 11:00.
    s.advance_to(at(8, 30))
    s.declare_mffd(3, Pathway.P0, DOCTOR, letter_eta=at(9, 0))
    s.advance_to(at(8, 40))
    s.request_tto(3, NURSE)
    s.advance_to(at(9, 0))
    s.apply_event("letter_signed", {"bed": 3, "doctor": "dr-raj"})
    s.advance_to(at(9, 10))
    p3 = s.plan(3)
    for kind in (TaskKind.FAMILY_INFORMED, TaskKind.BELONGINGS):
        s.update_task(3, e.find_task(p3, kind).id, TaskStatus.DONE, NURSE)
    s.advance_to(at(9, 15))
    b = s.request_booking(3, at(11, 0), Actor("transport", Role.TRANSPORT, ActorType.AGENT))
    s.advance_to(at(9, 16))
    s.confirm_booking(3, b.id, b.approval_id, NURSE)

    s.advance_to(DEMO_START)
    return s


SCENARIOS = {"margaret": ward7}


def build(name: str = "margaret") -> Store:
    if name not in SCENARIOS:
        raise KeyError(name)
    return SCENARIOS[name]()
