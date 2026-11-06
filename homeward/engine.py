"""Readiness engine (P1). Pure functions over the contract types.

Rules:
- No I/O and no wall clock: every function that needs time takes `now`.
- Every state change goes through `apply_transition`, which validates it and returns ledger entries.
- Non-clinical guarantee: human-only tasks (letter signing) can only be completed by a HUMAN with the owner role.
- Approval guarantee: a task waiting for approval (AWAITING_APPROVAL) can only be completed by a HUMAN.
Times are timezone-aware UTC. The demo is set in November, when UK time equals UTC.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from homeward.contracts import (
    BED_HOUR_GBP, DEPENDS_ON, NUDGES_BEFORE_ESCALATION, OWNER_ROLE, PATHWAY_TASKS,
    PICKUP_BUFFER_MIN, TARGET_MET_AT, TARGET_MINUTES, Actor, ActorType, Blocker, ErrorCode, HomewardError,
    LedgerEntry, Pathway, Patient, Role, Task, TaskKind, TaskStatus, can_transition, is_human_only,
)

ENGINE = Actor(id="engine", role=Role.BED_MANAGER, type=ActorType.SYSTEM)

TASK_LABEL: dict[TaskKind, str] = {
    TaskKind.TTO_VERIFY: "TTO verification",
    TaskKind.TTO_DISPENSE: "TTO dispensing",
    TaskKind.LETTER_SIGNED: "discharge letter signature",
    TaskKind.TRANSPORT_BOOKED: "transport booking",
    TaskKind.FAMILY_INFORMED: "family informed",
    TaskKind.BELONGINGS: "belongings packed",
    TaskKind.CARE_START_CONFIRMED: "care package start",
    TaskKind.EQUIPMENT: "equipment at home",
    TaskKind.HANDOVER_PACK_SENT: "handover pack sent",
}

OPEN = {TaskStatus.PENDING, TaskStatus.READY, TaskStatus.IN_PROGRESS,
        TaskStatus.AWAITING_APPROVAL, TaskStatus.BLOCKED}
# Statuses in which the target-time clock is running.
TIMED = {TaskStatus.READY, TaskStatus.IN_PROGRESS, TaskStatus.AWAITING_APPROVAL, TaskStatus.BLOCKED}
FINISHED = {TaskStatus.DONE, TaskStatus.CANCELLED}


# --- helpers -------------------------------------------------------------------
def _hhmm(t: Optional[datetime]) -> str:
    return t.strftime("%H:%M") if t else "unknown"


def _first_name(p: Patient) -> str:
    return p.name.split()[0]


def get_task(p: Patient, task_id: str) -> Task:
    for t in p.tasks:
        if t.id == task_id:
            return t
    raise HomewardError(ErrorCode.NOT_FOUND, f"no task {task_id} for bed {p.bed}", {"task_id": task_id})


def find_task(p: Patient, kind: TaskKind) -> Optional[Task]:
    return next((t for t in p.tasks if t.kind == kind), None)


def _deps_done(p: Patient, t: Task) -> bool:
    return all(get_task(p, d).status == TaskStatus.DONE for d in t.depends_on)


def _entry(p: Patient, actor: Actor, action: str, now: datetime, task: Optional[Task] = None,
           detail: Optional[str] = None, approval_id: Optional[str] = None) -> LedgerEntry:
    return LedgerEntry(actor=actor, action=action, at=now, bed=p.bed,
                       task_id=task.id if task else None, approval_id=approval_id, detail=detail)


# --- plan ----------------------------------------------------------------------
def build_plan(bed: int, name: str, pathway: Pathway, fit_at: datetime) -> Patient:
    """Create the task plan for a patient declared medically fit at `fit_at`."""
    kinds = PATHWAY_TASKS[pathway]
    ids = {k: f"t{i}" for i, k in enumerate(kinds, start=1)}
    tasks = []
    for k in kinds:
        deps = [ids[d] for d in DEPENDS_ON[k]]
        tasks.append(Task(
            id=ids[k], kind=k,
            status=TaskStatus.PENDING if deps else TaskStatus.READY,
            owner_role=OWNER_ROLE[k], depends_on=deps, human_only=is_human_only(k),
            target_minutes=TARGET_MINUTES.get(k),
            ready_at=None if deps else fit_at,
        ))
    return Patient(bed=bed, name=name, pathway=pathway, fit_at=fit_at, tasks=tasks)


# --- transitions -----------------------------------------------------------------
def apply_transition(p: Patient, task_id: str, dst: TaskStatus, actor: Actor, now: datetime,
                     eta: Optional[datetime] = None, approval_id: Optional[str] = None,
                     detail: Optional[str] = None) -> list[LedgerEntry]:
    """Validate and apply one status change. Returns ledger entries (the change, plus any
    dependants promoted to READY). Raises HomewardError and changes nothing if invalid."""
    if p.departed_at is not None:
        raise HomewardError(ErrorCode.VALIDATION, f"bed {p.bed} has already departed", {"bed": p.bed})
    t = get_task(p, task_id)
    src = t.status
    if not can_transition(src, dst):
        raise HomewardError(ErrorCode.INVALID_TRANSITION, f"{t.id} cannot go {src.value} -> {dst.value}",
                            {"task_id": t.id, "from": src.value, "to": dst.value})
    if dst in (TaskStatus.IN_PROGRESS, TaskStatus.AWAITING_APPROVAL, TaskStatus.DONE) and not _deps_done(p, t):
        raise HomewardError(ErrorCode.DEPENDENCY_UNMET, f"{t.id} depends on unfinished tasks",
                            {"task_id": t.id, "depends_on": t.depends_on})
    approving = src == TaskStatus.AWAITING_APPROVAL and dst in (TaskStatus.IN_PROGRESS, TaskStatus.DONE)
    if approving and actor.type != ActorType.HUMAN:
        raise HomewardError(ErrorCode.APPROVAL_REQUIRED, f"{t.id} needs a human approval",
                            {"task_id": t.id})
    if dst == TaskStatus.DONE:
        if t.human_only and not (actor.type == ActorType.HUMAN and actor.role == t.owner_role):
            raise HomewardError(ErrorCode.HUMAN_ONLY,
                                f"{TASK_LABEL[t.kind]} is a clinical task: only a {t.owner_role.value} can complete it",
                                {"task_id": t.id, "owner_role": t.owner_role.value})
        if actor.type == ActorType.HUMAN and actor.role not in (t.owner_role, Role.NURSE):
            raise HomewardError(ErrorCode.FORBIDDEN_ROLE,
                                f"a {actor.role.value} cannot complete {TASK_LABEL[t.kind]}",
                                {"task_id": t.id, "owner_role": t.owner_role.value})

    t.status = dst
    if eta is not None:
        t.eta = eta
    if dst == TaskStatus.DONE:
        t.eta = now  # actual completion time
    if dst == TaskStatus.BLOCKED:  # something external broke it: the clock restarts from now
        t.ready_at, t.nudges = now, 0
    entries = [_entry(p, actor, f"task.{dst.value}", now, t, detail=detail, approval_id=approval_id)]

    if dst == TaskStatus.DONE:
        for other in p.tasks:
            if other.status == TaskStatus.PENDING and t.id in other.depends_on and _deps_done(p, other):
                other.status, other.ready_at = TaskStatus.READY, now
                entries.append(_entry(p, ENGINE, "task.ready", now, other, detail=f"unblocked by {t.id}"))
    return entries


def check_pickup(slot: datetime, tto_eta: Optional[datetime], letter_eta: Optional[datetime]) -> datetime:
    """Transport must not arrive before the medicines and the letter are ready (+ buffer).
    Returns the earliest allowed pickup; raises PICKUP_TOO_EARLY otherwise."""
    known = [e for e in (tto_eta, letter_eta) if e is not None]
    if not known:
        raise HomewardError(ErrorCode.VALIDATION, "cannot time transport: no TTO or letter ETA yet", {})
    earliest = max(known) + timedelta(minutes=PICKUP_BUFFER_MIN)
    if slot < earliest:
        raise HomewardError(ErrorCode.PICKUP_TOO_EARLY,
                            f"pickup {_hhmm(slot)} is before {_hhmm(earliest)} (meds/letter ready + {PICKUP_BUFFER_MIN} min)",
                            {"slot": slot.isoformat(), "earliest": earliest.isoformat()})
    return earliest


# --- views -----------------------------------------------------------------------
def blocker(p: Patient, now: datetime) -> Blocker:
    """The single thing the patient is waiting on: a BLOCKED task first, else the open task
    with the latest ETA (an unknown ETA counts as latest), ties broken by plan order."""
    first = _first_name(p)
    if p.departed_at:
        return Blocker(p.bed, None, f"{first} went home at {_hhmm(p.departed_at)}.", None, None)
    open_tasks = [t for t in p.tasks if t.status in OPEN]
    if not open_tasks:
        return Blocker(p.bed, None, f"{first} is ready to go home. Nothing is outstanding.", None, None)
    order = {t.id: i for i, t in enumerate(p.tasks)}
    blocked = [t for t in open_tasks if t.status == TaskStatus.BLOCKED]
    if blocked:
        t = min(blocked, key=lambda x: order[x.id])
    else:
        far = datetime.max.replace(tzinfo=now.tzinfo)
        t = max(open_tasks, key=lambda x: (x.eta or far, -order[x.id]))
    state = "BLOCKED: " if t.status == TaskStatus.BLOCKED else ""
    summary = (f"{first} is waiting on: {state}{TASK_LABEL[t.kind]} (ETA {_hhmm(t.eta)}). "
               f"Owner: {t.owner_role.value}.")
    return Blocker(p.bed, t.id, summary, t.owner_role, t.eta)


def _clock_running(t: Task) -> bool:
    """Is this task's target clock running? Not before it is ready, and not once its target is met."""
    if t.status not in TIMED or not t.target_minutes or t.ready_at is None:
        return False
    return TARGET_MET_AT.get(t.kind) != t.status


def tick(p: Patient, now: datetime) -> list[LedgerEntry]:
    """Apply due nudges and escalations. Idempotent for a given `now`.
    Thresholds from when the task became ready: nudge at target, nudge at 1.5x, escalate to
    bed manager at 2x (after NUDGES_BEFORE_ESCALATION nudges)."""
    entries: list[LedgerEntry] = []
    if p.departed_at:
        return entries
    for t in p.tasks:
        if not _clock_running(t):
            continue
        elapsed = (now - t.ready_at).total_seconds() / 60
        thresholds = [t.target_minutes * f for f in (1.0, 1.5)][:NUDGES_BEFORE_ESCALATION] + [t.target_minutes * 2.0]
        while t.nudges < len(thresholds) and elapsed >= thresholds[t.nudges]:
            t.nudges += 1
            if t.nudges <= NUDGES_BEFORE_ESCALATION:
                entries.append(_entry(p, ENGINE, "nudge", now, t,
                                      detail=f"nudge {t.nudges} to {t.owner_role.value}: {TASK_LABEL[t.kind]} "
                                             f"over target ({t.target_minutes} min)"))
            else:
                entries.append(_entry(p, ENGINE, "escalation", now, t,
                                      detail=f"escalated to bed_manager: {TASK_LABEL[t.kind]} "
                                             f"{int(elapsed)} min since ready (target {t.target_minutes})"))
    return entries


def overdue(p: Patient, now: datetime) -> list[str]:
    """Ids of timed tasks past their target (for the board's amber state)."""
    return [t.id for t in p.tasks
            if _clock_running(t) and (now - t.ready_at) >= timedelta(minutes=t.target_minutes)]


def cost(p: Patient, now: datetime) -> dict:
    """Bed-hours and GBP since the patient became medically fit."""
    end = p.departed_at or now
    hours = max(0.0, (end - p.fit_at).total_seconds() / 3600)
    return {"hours": round(hours, 2), "gbp": round(hours * BED_HOUR_GBP, 2)}


def can_depart(p: Patient) -> bool:
    return p.departed_at is None and all(t.status in FINISHED for t in p.tasks)


def depart(p: Patient, actor: Actor, now: datetime) -> LedgerEntry:
    """Record departure. Only a human can confirm it, and only when every task is finished."""
    if actor.type != ActorType.HUMAN:
        raise HomewardError(ErrorCode.APPROVAL_REQUIRED, "a human must confirm departure", {"bed": p.bed})
    if not can_depart(p):
        open_ids = [t.id for t in p.tasks if t.status not in FINISHED]
        raise HomewardError(ErrorCode.DEPENDENCY_UNMET, f"bed {p.bed} still has open tasks",
                            {"open": open_ids})
    p.departed_at = now
    return _entry(p, actor, "patient.departed", now)


def handover_summary(p: Patient, now: datetime) -> str:
    """One-message shift handover (I-PASS style): status, open actions with owners, next deadline."""
    c = cost(p, now)
    b = blocker(p, now)
    lines = [f"Bed {p.bed} {p.name} ({p.pathway.value}), medically fit since {_hhmm(p.fit_at)} "
             f"({c['hours']} bed-hours, £{c['gbp']:.0f}).",
             f"Now: {b.summary}"]
    open_tasks = [t for t in p.tasks if t.status in OPEN]
    if open_tasks:
        lines.append("Open:")
        for t in open_tasks:
            flag = " [clinical, human only]" if t.human_only else ""
            lines.append(f"- {TASK_LABEL[t.kind]}: {t.status.value}, owner {t.owner_role.value}, "
                         f"ETA {_hhmm(t.eta)}{flag}")
    deadlines = [(t.ready_at + timedelta(minutes=t.target_minutes), t) for t in open_tasks
                 if _clock_running(t)]
    if deadlines:
        when, t = min(deadlines, key=lambda x: x[0])
        lines.append(f"Next deadline: {TASK_LABEL[t.kind]} by {_hhmm(when)}.")
    done = sum(1 for t in p.tasks if t.status == TaskStatus.DONE)
    lines.append(f"Done: {done}/{len(p.tasks)} tasks.")
    return "\n".join(lines)
