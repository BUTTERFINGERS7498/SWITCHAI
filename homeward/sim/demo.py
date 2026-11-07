"""Presenter beats for filming: Margaret's day, one beat at a time, through the same Store operations as
`scenario margaret --auto`. Used by `POST /demo/next` and the board's presenter mode (`/board?presenter=1`,
key `n`). It replays what the agents and the nurse did in the live Slack run; it is not a different engine."""
from __future__ import annotations

from datetime import datetime, timedelta

from homeward import engine as e
from homeward.contracts import Actor, ActorType, Pathway, Role, TaskKind, TaskStatus
from homeward.sim.state import Store

DAY = "2026-11-07T"
DOCTOR = Actor("dr-raj", Role.DOCTOR, ActorType.HUMAN)
NURSE = Actor("nurse-amy", Role.NURSE, ActorType.HUMAN)
LEAD = Actor("discharge-lead", Role.COORDINATOR, ActorType.AGENT)
MEDS = Actor("pharmacy-liaison", Role.COORDINATOR, ActorType.AGENT)
TRANSPORT = Actor("transport-liaison", Role.COORDINATOR, ActorType.AGENT)
BED = 12


def _t(hhmm: str) -> datetime:
    return datetime.fromisoformat(f"{DAY}{hhmm}:00+00:00")


def _book_first_safe_slot(s: Store):
    p = s.plan(BED)
    tto, letter = e.find_task(p, TaskKind.TTO_DISPENSE), e.find_task(p, TaskKind.LETTER_SIGNED)
    earliest = max(x for x in (tto.eta, letter.eta) if x) + timedelta(minutes=e.PICKUP_BUFFER_MIN)
    vehicle = s.eligibility(BED)["vehicle"]
    slot = datetime.fromisoformat(s.slots(vehicle, earliest)[0])
    b = s.request_booking(BED, slot, TRANSPORT)
    s.confirm_booking(BED, b.id, b.approval_id, NURSE)


def _fit(s: Store):
    s.declare_mffd(BED, Pathway.P0, DOCTOR)


def _agents_work(s: Store):
    s.advance_to(_t("10:05"))
    s.request_tto(BED, MEDS)
    _book_first_safe_slot(s)
    p = s.plan(BED)
    s.update_task(BED, e.find_task(p, TaskKind.FAMILY_INFORMED).id, TaskStatus.DONE, LEAD,
                  detail="reported by nurse-amy: daughter Sarah told 10:05")
    s.update_task(BED, e.find_task(p, TaskKind.BELONGINGS).id, TaskStatus.DONE, LEAD,
                  detail="reported by nurse-amy: belongings packed 10:05")


def _letter(s: Store):
    s.advance_to(_t("11:00"))
    s.apply_event("letter_signed", {"bed": BED, "doctor": "dr-raj"})


def _cancel(s: Store):
    s.apply_event("transport_cancelled", {"bed": BED, "at": _t("11:20"), "reason": "vehicle breakdown"})
    s.advance_to(_t("11:20"))


def _rebook(s: Store):
    s.advance_to(_t("11:22"))
    _book_first_safe_slot(s)


def _home(s: Store):
    b = [x for x in s.bookings.values() if x.bed == BED and x.status == "confirmed"][-1]
    s.advance_to(b.slot + timedelta(minutes=10))


BEATS = [
    ("10:00 Doctor declares Margaret medically fit (EPR)", _fit),
    ("10:05 Agents request medicines, book transport with a nurse's approval, record family and belongings", _agents_work),
    ("11:00 Letter signed in the EPR", _letter),
    ("11:20 Transport provider cancels", _cancel),
    ("11:22 Transport rebooked, nurse approves", _rebook),
    ("Margaret goes home", _home),
]


def next_beat(s: Store, done: int) -> tuple[int, str]:
    """Run beat number `done` (0-based). Returns (new count, label). Past the end, does nothing."""
    if done >= len(BEATS):
        return done, "end of the day"
    label, fn = BEATS[done]
    fn(s)
    return done + 1, label
