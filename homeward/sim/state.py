"""In-memory simulated hospital (P2).

The Store owns all state and the single scenario clock. Every task change goes through the
engine. Simulated hospital systems (pharmacy, transport crews, the EPR where doctors sign
letters) act on the clock through scheduled events; agents never act as those people.
"""
from __future__ import annotations

import heapq
import itertools
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

from homeward import engine as e
from homeward.contracts import (
    Actor, ActorType, ErrorCode, HomewardError, LedgerEntry, Pathway, Patient, Role, TaskKind,
    TaskStatus, to_wire,
)

# Simulated hospital systems (SYSTEM actors) and real-world humans the sim stands in for.
PHARMACY_SYSTEM = Actor("pharmacy-system", Role.PHARMACIST, ActorType.SYSTEM)
TRANSPORT_SYSTEM = Actor("transport-system", Role.TRANSPORT, ActorType.SYSTEM)
CREW = Actor("ambulance-crew", Role.TRANSPORT, ActorType.HUMAN)
SIM = Actor("sim", Role.BED_MANAGER, ActorType.SYSTEM)

VEHICLES = ("car", "wheelchair", "stretcher")
SLOT_MINUTES = 15
LOAD_MINUTES = 10          # crew arrival -> patient leaves the ward


@dataclass
class Inpatient:
    bed: int
    name: str
    age: int
    mobility: str          # "independent" | "wheelchair" | "stretcher"
    oxygen: bool = False
    escort: bool = False
    next_of_kin: str = ""
    baseline_departure: Optional[datetime] = None   # when this patient left without Homeward (story baseline)


@dataclass
class Tto:
    status: str = "not_requested"   # not_requested | verifying | dispensing | ready
    requested_at: Optional[datetime] = None
    priority: str = "routine"
    verify_minutes: int = 50
    dispense_minutes: int = 55
    verified_eta: Optional[datetime] = None
    ready_eta: Optional[datetime] = None


@dataclass
class Booking:
    id: str
    bed: int
    vehicle: str
    slot: datetime
    status: str                      # pending_approval | confirmed | cancelled | declined | completed
    approval_id: str
    requested_by: str
    approved_by: Optional[str] = None


@dataclass(order=True)
class _Event:
    at: datetime
    seq: int
    kind: str = field(compare=False)
    data: dict = field(compare=False, default_factory=dict)


def vehicle_for(ip: Inpatient) -> str:
    return {"independent": "car", "wheelchair": "wheelchair", "stretcher": "stretcher"}[ip.mobility]


class Store:
    def __init__(self, now: datetime):
        self.lock = threading.RLock()
        self.clock = now
        self.created_at = now   # approvals counted from here (seeded history included)
        self.inpatients: dict[int, Inpatient] = {}
        self.plans: dict[int, Patient] = {}
        self.tto: dict[int, Tto] = {}
        self.bookings: dict[str, Booking] = {}
        self.taken_slots: set[tuple[str, datetime]] = set()
        self.ledger: list[LedgerEntry] = []
        self._events: list[_Event] = []
        self._seq = itertools.count()
        self._booking_ids = itertools.count(1)
        self._approval_ids = itertools.count(1)

    # --- basics ------------------------------------------------------------------
    def add_inpatient(self, ip: Inpatient, tto: Optional[Tto] = None):
        self.inpatients[ip.bed] = ip
        self.tto[ip.bed] = tto or Tto()

    def inpatient(self, bed: int) -> Inpatient:
        if bed not in self.inpatients:
            raise HomewardError(ErrorCode.NOT_FOUND, f"no patient in bed {bed}", {"bed": bed})
        return self.inpatients[bed]

    def plan(self, bed: int) -> Patient:
        self.inpatient(bed)
        if bed not in self.plans:
            raise HomewardError(ErrorCode.NOT_FOUND, f"bed {bed} has not been declared medically fit",
                                {"bed": bed})
        return self.plans[bed]

    def _log(self, entries):
        self.ledger.extend(entries)

    def _schedule(self, at: datetime, kind: str, **data):
        heapq.heappush(self._events, _Event(at, next(self._seq), kind, data))

    # --- clock -------------------------------------------------------------------
    def advance_to(self, target: datetime) -> list[LedgerEntry]:
        """Move the clock forward, firing scheduled events in time order and ticking timers."""
        if target < self.clock:
            raise HomewardError(ErrorCode.VALIDATION, "the clock only moves forward",
                                {"now": self.clock.isoformat(), "requested": target.isoformat()})
        start = len(self.ledger)
        while self._events and self._events[0].at <= target:
            ev = heapq.heappop(self._events)
            self.clock = max(self.clock, ev.at)
            self._tick_all()
            self._fire(ev)
        self.clock = target
        self._tick_all()
        return self.ledger[start:]

    def _tick_all(self):
        for p in self.plans.values():
            self._log(e.tick(p, self.clock))

    def _fire(self, ev: _Event):
        bed = ev.data.get("bed")
        p = self.plans.get(bed)
        if ev.kind == "tto_verified" and p:
            tto = self.tto[bed]
            if tto.status != "verifying" or tto.verified_eta != ev.at:
                return  # superseded by a delay
            v = e.find_task(p, TaskKind.TTO_VERIFY)
            self._log(e.apply_transition(p, v.id, TaskStatus.DONE, PHARMACY_SYSTEM, self.clock,
                                         detail="TTO verified by pharmacist"))
            d = e.find_task(p, TaskKind.TTO_DISPENSE)
            tto.status = "dispensing"
            self._log(e.apply_transition(p, d.id, TaskStatus.IN_PROGRESS, PHARMACY_SYSTEM, self.clock,
                                         eta=tto.ready_eta, detail="dispensing started"))
            self._schedule(tto.ready_eta, "tto_ready", bed=bed)
        elif ev.kind == "tto_ready" and p:
            tto = self.tto[bed]
            if tto.status != "dispensing" or tto.ready_eta != ev.at:
                return
            d = e.find_task(p, TaskKind.TTO_DISPENSE)
            tto.status = "ready"
            self._log(e.apply_transition(p, d.id, TaskStatus.DONE, PHARMACY_SYSTEM, self.clock,
                                         detail="TTO ready for collection on the ward"))
        elif ev.kind == "pickup":
            self._pickup(ev.data["booking_id"])
        elif ev.kind == "departure" and p:
            if e.can_depart(p):
                self._log([e.depart(p, CREW, self.clock)])
        elif ev.kind == "external":
            self.apply_event(ev.data["type"], ev.data)

    def _pickup(self, booking_id: str):
        b = self.bookings[booking_id]
        if b.status != "confirmed":
            return
        p = self.plans[b.bed]
        tr = e.find_task(p, TaskKind.TRANSPORT_BOOKED)
        others_done = all(t.status in e.FINISHED for t in p.tasks if t.id != tr.id)
        if not others_done:
            # The classic failure: crew arrives, patient isn't ready, crew leaves.
            b.status = "cancelled"
            self._log(e.apply_transition(p, tr.id, TaskStatus.BLOCKED, CREW, self.clock,
                                         detail="crew arrived but patient not ready; crew left"))
            return
        b.status = "completed"
        self._log(e.apply_transition(p, tr.id, TaskStatus.DONE, CREW, self.clock,
                                     detail=f"crew collected patient ({b.vehicle})"))
        self._schedule(self.clock + timedelta(minutes=LOAD_MINUTES), "departure", bed=b.bed)

    # --- MFFD --------------------------------------------------------------------
    def declare_mffd(self, bed: int, pathway: Pathway, actor: Actor,
                     letter_eta: Optional[datetime] = None) -> Patient:
        ip = self.inpatient(bed)
        if actor.type != ActorType.HUMAN or actor.role != Role.DOCTOR:
            raise HomewardError(ErrorCode.HUMAN_ONLY, "only a doctor can declare a patient medically fit",
                                {"bed": bed})
        if bed in self.plans:
            raise HomewardError(ErrorCode.VALIDATION, f"bed {bed} is already declared fit", {"bed": bed})
        p = e.build_plan(bed, ip.name, pathway, self.clock)
        letter = e.find_task(p, TaskKind.LETTER_SIGNED)
        letter.eta = letter_eta or self.clock + timedelta(minutes=60)
        if self.tto[bed].status == "not_requested":
            self.tto[bed].ready_eta = None
        self.plans[bed] = p
        self._log([LedgerEntry(actor, "patient.mffd", self.clock, bed, detail=f"pathway {pathway.value}")])
        return p

    # --- tasks ---------------------------------------------------------------------
    def update_task(self, bed: int, task_id: str, status: TaskStatus, actor: Actor,
                    eta: Optional[datetime] = None, detail: Optional[str] = None) -> list[LedgerEntry]:
        p = self.plan(bed)
        t = e.get_task(p, task_id)
        if t.kind in (TaskKind.TTO_VERIFY, TaskKind.TTO_DISPENSE) and actor.type == ActorType.AGENT:
            raise HomewardError(ErrorCode.FORBIDDEN_ROLE,
                                "TTO status comes from the pharmacy system; use POST /patients/{bed}/tto/request",
                                {"task_id": task_id})
        if t.kind == TaskKind.TRANSPORT_BOOKED and status in (TaskStatus.IN_PROGRESS, TaskStatus.DONE):
            raise HomewardError(ErrorCode.APPROVAL_REQUIRED,
                                "transport is confirmed through a booking approval", {"task_id": task_id})
        entries = e.apply_transition(p, task_id, status, actor, self.clock, eta=eta, detail=detail)
        self._log(entries)
        return entries

    # --- pharmacy ------------------------------------------------------------------
    def request_tto(self, bed: int, actor: Actor, priority: str = "routine") -> Tto:
        p = self.plan(bed)
        tto = self.tto[bed]
        if tto.status != "not_requested":
            raise HomewardError(ErrorCode.VALIDATION, f"TTO for bed {bed} already requested ({tto.status})",
                                {"bed": bed, "status": tto.status})
        tto.status, tto.requested_at, tto.priority = "verifying", self.clock, priority
        tto.verified_eta = self.clock + timedelta(minutes=tto.verify_minutes)
        tto.ready_eta = tto.verified_eta + timedelta(minutes=tto.dispense_minutes)
        v = e.find_task(p, TaskKind.TTO_VERIFY)
        self._log(e.apply_transition(p, v.id, TaskStatus.IN_PROGRESS, actor, self.clock,
                                     eta=tto.verified_eta, detail=f"TTO request sent to pharmacy ({priority})"))
        e.find_task(p, TaskKind.TTO_DISPENSE).eta = tto.ready_eta
        self._schedule(tto.verified_eta, "tto_verified", bed=bed)
        return tto

    def delay_tto(self, bed: int, minutes: int):
        tto = self.tto[bed]
        p = self.plan(bed)
        if tto.status == "verifying":
            tto.verified_eta += timedelta(minutes=minutes)
            tto.ready_eta += timedelta(minutes=minutes)
            e.find_task(p, TaskKind.TTO_VERIFY).eta = tto.verified_eta
            self._schedule(tto.verified_eta, "tto_verified", bed=bed)
        elif tto.status == "dispensing":
            tto.ready_eta += timedelta(minutes=minutes)
            self._schedule(tto.ready_eta, "tto_ready", bed=bed)
        else:
            raise HomewardError(ErrorCode.VALIDATION, f"TTO for bed {bed} is {tto.status}", {})
        e.find_task(p, TaskKind.TTO_DISPENSE).eta = tto.ready_eta
        self._log([LedgerEntry(PHARMACY_SYSTEM, "tto.delayed", self.clock, bed,
                               detail=f"TTO delayed {minutes} min, ready {tto.ready_eta:%H:%M}")])

    # --- transport -------------------------------------------------------------------
    def eligibility(self, bed: int) -> dict:
        ip = self.inpatient(bed)
        return {"bed": bed, "vehicle": vehicle_for(ip), "mobility": ip.mobility,
                "oxygen": ip.oxygen, "escort": ip.escort}

    def slots(self, vehicle: str, after: Optional[datetime] = None, limit: int = 12) -> list[str]:
        if vehicle not in VEHICLES:
            raise HomewardError(ErrorCode.VALIDATION, f"unknown vehicle {vehicle}", {"vehicles": list(VEHICLES)})
        start = max(after or self.clock, self.clock)
        day = start.replace(hour=11, minute=0, second=0, microsecond=0)
        end = start.replace(hour=18, minute=0, second=0, microsecond=0)
        out, t = [], day
        while t <= end and len(out) < limit:
            if t >= start and (vehicle, t) not in self.taken_slots:
                out.append(t.isoformat())
            t += timedelta(minutes=SLOT_MINUTES)
        return out

    def request_booking(self, bed: int, slot: datetime, actor: Actor, vehicle: Optional[str] = None) -> Booking:
        p = self.plan(bed)
        need = vehicle_for(self.inpatient(bed))
        vehicle = vehicle or need
        if vehicle != need:
            raise HomewardError(ErrorCode.VALIDATION, f"bed {bed} needs a {need} vehicle, not {vehicle}",
                                {"needed": need})
        if slot.minute % SLOT_MINUTES or slot.second or (vehicle, slot) in self.taken_slots \
                or slot <= self.clock or not (11 <= slot.hour < 18 or (slot.hour == 18 and slot.minute == 0)):
            raise HomewardError(ErrorCode.VALIDATION, f"slot {slot:%H:%M} is not available",
                                {"available": self.slots(vehicle)[:6]})
        tto, letter = e.find_task(p, TaskKind.TTO_DISPENSE), e.find_task(p, TaskKind.LETTER_SIGNED)
        e.check_pickup(slot, tto.eta, letter.eta)
        tr = e.find_task(p, TaskKind.TRANSPORT_BOOKED)
        if any(b.bed == bed and b.status in ("pending_approval", "confirmed") for b in self.bookings.values()):
            raise HomewardError(ErrorCode.VALIDATION, f"bed {bed} already has an active booking", {})
        if tr.status == TaskStatus.BLOCKED:  # rebook after a cancellation
            self._log(e.apply_transition(p, tr.id, TaskStatus.READY, actor, self.clock, detail="rebooking"))
        b = Booking(id=f"B-{next(self._booking_ids)}", bed=bed, vehicle=vehicle, slot=slot,
                    status="pending_approval", approval_id=f"A-{next(self._approval_ids)}", requested_by=actor.id)
        self._log(e.apply_transition(p, tr.id, TaskStatus.AWAITING_APPROVAL, actor, self.clock, eta=slot,
                                     approval_id=b.approval_id,
                                     detail=f"{vehicle} pickup {slot:%H:%M} requested ({b.id})"))
        self.bookings[b.id] = b
        self.taken_slots.add((vehicle, slot))
        return b

    def confirm_booking(self, bed: int, booking_id: str, approval_id: str, approver: Actor) -> Booking:
        p = self.plan(bed)
        b = self.bookings.get(booking_id)
        if not b or b.bed != bed:
            raise HomewardError(ErrorCode.NOT_FOUND, f"no booking {booking_id} for bed {bed}", {})
        if b.status != "pending_approval":
            raise HomewardError(ErrorCode.VALIDATION, f"booking {booking_id} is {b.status}", {})
        if approval_id != b.approval_id:
            raise HomewardError(ErrorCode.VALIDATION, "approval id does not match this booking",
                                {"expected": b.approval_id})
        if approver.type != ActorType.HUMAN or approver.role != Role.NURSE:
            raise HomewardError(ErrorCode.APPROVAL_REQUIRED, "only a nurse can approve a transport booking",
                                {"approval_id": approval_id})
        tr = e.find_task(p, TaskKind.TRANSPORT_BOOKED)
        self._log(e.apply_transition(p, tr.id, TaskStatus.IN_PROGRESS, approver, self.clock, eta=b.slot,
                                     approval_id=approval_id, detail=f"booking {b.id} approved, pickup {b.slot:%H:%M}"))
        b.status, b.approved_by = "confirmed", approver.id
        self._schedule(b.slot, "pickup", booking_id=b.id)
        return b

    def decline_booking(self, bed: int, booking_id: str, approver: Actor) -> Booking:
        p = self.plan(bed)
        b = self.bookings.get(booking_id)
        if not b or b.bed != bed or b.status != "pending_approval":
            raise HomewardError(ErrorCode.NOT_FOUND, f"no pending booking {booking_id} for bed {bed}", {})
        tr = e.find_task(p, TaskKind.TRANSPORT_BOOKED)
        self._log(e.apply_transition(p, tr.id, TaskStatus.READY, approver, self.clock,
                                     approval_id=b.approval_id, detail=f"booking {b.id} declined"))
        b.status = "declined"
        self.taken_slots.discard((b.vehicle, b.slot))
        return b

    # --- external events (scenario injection) ----------------------------------------
    def apply_event(self, kind: str, data: dict) -> list[LedgerEntry]:
        """Things that happen in the real world outside the chat."""
        at = data.get("at")
        if at and at > self.clock:
            payload = {k: v for k, v in data.items() if k != "at"}
            self._schedule(at, "external", **payload, type=kind)
            return []
        bed = data.get("bed")
        start = len(self.ledger)
        if kind == "transport_cancelled":
            p = self.plan(bed)
            active = [b for b in self.bookings.values() if b.bed == bed and b.status in ("pending_approval", "confirmed")]
            if not active:
                raise HomewardError(ErrorCode.VALIDATION, f"bed {bed} has no active booking to cancel", {})
            b = active[0]
            b.status = "cancelled"
            tr = e.find_task(p, TaskKind.TRANSPORT_BOOKED)
            self._log(e.apply_transition(p, tr.id, TaskStatus.BLOCKED, TRANSPORT_SYSTEM, self.clock,
                                         detail=f"transport provider cancelled {b.id} ({data.get('reason') or 'no vehicle available'})"))
        elif kind == "letter_signed":
            p = self.plan(bed)
            doctor = Actor(data.get("doctor") or "dr-on-call", Role.DOCTOR, ActorType.HUMAN)
            letter = e.find_task(p, TaskKind.LETTER_SIGNED)
            self._log(e.apply_transition(p, letter.id, TaskStatus.DONE, doctor, self.clock,
                                         detail="discharge letter signed in the EPR"))
        elif kind == "tto_delayed":
            self.delay_tto(bed, int(data.get("minutes") or 30))
        else:
            raise HomewardError(ErrorCode.VALIDATION, f"unknown event {kind}",
                                {"known": ["transport_cancelled", "letter_signed", "tto_delayed"]})
        return self.ledger[start:]

    # --- views -----------------------------------------------------------------------
    def patient_view(self, bed: int) -> dict:
        ip = self.inpatient(bed)
        out = {"bed": bed, "name": ip.name, "age": ip.age, "mobility": ip.mobility,
               "declared_fit": bed in self.plans,
               "baseline_departure": ip.baseline_departure.isoformat() if ip.baseline_departure else None}
        if bed in self.plans:
            p = self.plans[bed]
            out.update(pathway=p.pathway.value, fit_at=p.fit_at.isoformat(),
                       departed_at=p.departed_at.isoformat() if p.departed_at else None)
        return out

    def plan_view(self, bed: int) -> dict:
        p = self.plan(bed)
        tasks = []
        for t in p.tasks:
            w = to_wire(t)
            w["label"] = e.TASK_LABEL[t.kind]
            tasks.append(w)
        return {"bed": bed, "name": p.name, "pathway": p.pathway.value, "fit_at": p.fit_at.isoformat(),
                "departed_at": p.departed_at.isoformat() if p.departed_at else None, "tasks": tasks}

    def blocker_view(self, bed: int) -> dict:
        p = self.plan(bed)
        b = e.blocker(p, self.clock)
        return {**to_wire(b), "cost": e.cost(p, self.clock), "overdue": e.overdue(p, self.clock),
                "now": self.clock.isoformat()}

    def tto_view(self, bed: int) -> dict:
        self.inpatient(bed)
        return {"bed": bed, **to_wire(self.tto[bed])}

    def ledger_view(self, bed: Optional[int] = None, limit: Optional[int] = None) -> list[dict]:
        rows = [to_wire(x) for x in self.ledger if bed is None or x.bed == bed]
        return rows[-limit:] if limit else rows

    def booking_view(self, b: Booking) -> dict:
        return to_wire(b)

    def board(self) -> dict:
        beds = []
        for bed in sorted(self.inpatients):
            row = self.patient_view(bed)
            if bed in self.plans:
                p = self.plans[bed]
                tr = e.blocker(p, self.clock)
                row.update(blocker=tr.summary, blocker_task=tr.task_id, cost=e.cost(p, self.clock),
                           overdue=e.overdue(p, self.clock), tasks=self.plan_view(bed)["tasks"],
                           bookings=[to_wire(b) for b in self.bookings.values() if b.bed == bed])
            beds.append(row)
        lost = sum(e.cost(p, self.clock)["hours"] for p in self.plans.values())
        approvals = sum(1 for x in self.ledger
                        if x.approval_id and x.actor.type == ActorType.HUMAN and x.at >= self.created_at)
        agent_rows = [x for x in self.ledger if x.actor.type == ActorType.AGENT]
        clinical_kinds = {TaskKind.LETTER_SIGNED}
        clinical_by_agents = 0
        for x in agent_rows:
            p = self.plans.get(x.bed)
            t = next((t for t in p.tasks if t.id == x.task_id), None) if p and x.task_id else None
            if x.action == "patient.mffd" or (t is not None and t.kind in clinical_kinds):
                clinical_by_agents += 1
        freed = 0.0
        for bed, p in self.plans.items():
            base = self.inpatients[bed].baseline_departure
            if p.departed_at and base and base > p.departed_at:
                freed += (base - p.departed_at).total_seconds() / 3600
        return {"now": self.clock.isoformat(), "beds": beds,
                "totals": {"bed_hours": round(lost, 2), "gbp": round(lost * e.BED_HOUR_GBP, 2),
                           "approvals": approvals, "agent_actions": len(agent_rows),
                           "clinical_by_agents": clinical_by_agents,
                           "ready": sum(1 for p in self.plans.values() if not p.departed_at),
                           "home": sum(1 for p in self.plans.values() if p.departed_at),
                           "hours_freed": round(freed, 2)},
                "ledger": self.ledger_view(limit=12)}
