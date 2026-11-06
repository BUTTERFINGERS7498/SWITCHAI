"""Frozen shared contract for Homeward (TASK-001).

Stdlib only. Imported by the engine (TASK-002), the sim (TASK-003), the tool layer
(TASK-004) and the scenario runner (TASK-007). Changing anything here needs agreement
from both agents (see docs/DECISIONS.md). All times are timezone-aware UTC datetimes;
on the wire they are ISO-8601 strings. Engine functions never read the wall clock:
`now` is always passed in.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from typing import Optional

CONTRACT_VERSION = "1.2.0"

# --- Constants (from the dossier; illustrative, synthetic) -------------------
BED_DAY_GBP = 562.0
BED_HOUR_GBP = 23.42
PICKUP_BUFFER_MIN = 20          # pickup >= max(tto_ready_eta, letter_eta) + 20 min
NUDGES_BEFORE_ESCALATION = 2


class Pathway(str, Enum):
    P0 = "P0"  # home, no new support
    P1 = "P1"  # home with support
    P2 = "P2"  # rehab bed
    P3 = "P3"  # care home


class Role(str, Enum):
    DOCTOR = "doctor"
    NURSE = "nurse"
    PHARMACIST = "pharmacist"
    TRANSPORT = "transport"
    BED_MANAGER = "bed_manager"
    SOCIAL_WORKER = "social_worker"
    COORDINATOR = "coordinator"   # agents acting as themselves; never a clinical role


class ActorType(str, Enum):
    HUMAN = "human"
    AGENT = "agent"
    SYSTEM = "system"  # engine / scenario clock


class TaskKind(str, Enum):
    TTO_VERIFY = "tto_verify"
    TTO_DISPENSE = "tto_dispense"
    LETTER_SIGNED = "letter_signed"            # clinical: human only
    TRANSPORT_BOOKED = "transport_booked"
    FAMILY_INFORMED = "family_informed"
    BELONGINGS = "belongings"
    CARE_START_CONFIRMED = "care_start_confirmed"   # P1-P3
    EQUIPMENT = "equipment"                          # P1-P3
    HANDOVER_PACK_SENT = "handover_pack_sent"        # P1-P3


class TaskStatus(str, Enum):
    PENDING = "pending"                    # dependencies not met
    READY = "ready"                        # can start
    IN_PROGRESS = "in_progress"
    AWAITING_APPROVAL = "awaiting_approval"  # waiting for a human approval card
    DONE = "done"
    BLOCKED = "blocked"                    # external failure (e.g. booking cancelled)
    CANCELLED = "cancelled"


# Explicit transition table. Anything not listed is rejected with INVALID_TRANSITION.
TRANSITIONS: dict[TaskStatus, frozenset[TaskStatus]] = {
    TaskStatus.PENDING: frozenset({TaskStatus.READY, TaskStatus.CANCELLED}),
    TaskStatus.READY: frozenset({TaskStatus.IN_PROGRESS, TaskStatus.AWAITING_APPROVAL,
                                 TaskStatus.DONE, TaskStatus.BLOCKED, TaskStatus.CANCELLED}),
    TaskStatus.IN_PROGRESS: frozenset({TaskStatus.AWAITING_APPROVAL, TaskStatus.DONE,
                                       TaskStatus.BLOCKED, TaskStatus.CANCELLED}),
    # -> IN_PROGRESS = approved, now executing (e.g. transport booked, awaiting pickup)
    TaskStatus.AWAITING_APPROVAL: frozenset({TaskStatus.IN_PROGRESS, TaskStatus.DONE, TaskStatus.READY,
                                             TaskStatus.BLOCKED, TaskStatus.CANCELLED}),
    TaskStatus.BLOCKED: frozenset({TaskStatus.READY, TaskStatus.CANCELLED}),
    TaskStatus.DONE: frozenset(),
    TaskStatus.CANCELLED: frozenset(),
}

# Non-clinical guarantee, enforced in code: these tasks can only be completed by a
# HUMAN actor holding the owner role. Agents may read/track them, never complete them.
HUMAN_ONLY_KINDS: frozenset[TaskKind] = frozenset({TaskKind.LETTER_SIGNED})

OWNER_ROLE: dict[TaskKind, Role] = {
    TaskKind.TTO_VERIFY: Role.PHARMACIST,
    TaskKind.TTO_DISPENSE: Role.PHARMACIST,
    TaskKind.LETTER_SIGNED: Role.DOCTOR,
    TaskKind.TRANSPORT_BOOKED: Role.TRANSPORT,
    TaskKind.FAMILY_INFORMED: Role.NURSE,
    TaskKind.BELONGINGS: Role.NURSE,
    TaskKind.CARE_START_CONFIRMED: Role.SOCIAL_WORKER,
    TaskKind.EQUIPMENT: Role.SOCIAL_WORKER,
    TaskKind.HANDOVER_PACK_SENT: Role.NURSE,
}

# Task dependencies by kind (task X may start only when all its deps are DONE).
# Transport additionally obeys the pickup rule (see PICKUP_BUFFER_MIN).
DEPENDS_ON: dict[TaskKind, tuple[TaskKind, ...]] = {
    TaskKind.TTO_VERIFY: (),
    TaskKind.TTO_DISPENSE: (TaskKind.TTO_VERIFY,),
    TaskKind.LETTER_SIGNED: (),
    TaskKind.TRANSPORT_BOOKED: (),   # booked early, timed by pickup rule; departure needs all DONE
    TaskKind.FAMILY_INFORMED: (),
    TaskKind.BELONGINGS: (),
    TaskKind.CARE_START_CONFIRMED: (),
    TaskKind.EQUIPMENT: (),
    TaskKind.HANDOVER_PACK_SENT: (TaskKind.CARE_START_CONFIRMED,),
}

_CORE = (TaskKind.TTO_VERIFY, TaskKind.TTO_DISPENSE, TaskKind.LETTER_SIGNED,
         TaskKind.TRANSPORT_BOOKED, TaskKind.FAMILY_INFORMED, TaskKind.BELONGINGS)
_SUPPORT = (TaskKind.CARE_START_CONFIRMED, TaskKind.EQUIPMENT, TaskKind.HANDOVER_PACK_SENT)

PATHWAY_TASKS: dict[Pathway, tuple[TaskKind, ...]] = {
    Pathway.P0: _CORE,
    Pathway.P1: _CORE + _SUPPORT,
    Pathway.P2: _CORE + _SUPPORT,
    Pathway.P3: _CORE + _SUPPORT,
}

# Target minutes from task becoming READY; engine nudges twice then escalates to bed_manager.
TARGET_MINUTES: dict[TaskKind, Optional[int]] = {
    TaskKind.TTO_VERIFY: 60,
    TaskKind.TTO_DISPENSE: 90,
    TaskKind.TRANSPORT_BOOKED: 30,
}


# --- Domain types ------------------------------------------------------------
@dataclass
class Actor:
    id: str
    role: Role
    type: ActorType = ActorType.HUMAN


@dataclass
class Task:
    id: str
    kind: TaskKind
    status: TaskStatus
    owner_role: Role
    depends_on: list[str] = field(default_factory=list)   # task ids
    human_only: bool = False
    target_minutes: Optional[int] = None
    eta: Optional[datetime] = None
    ready_at: Optional[datetime] = None
    nudges: int = 0


@dataclass
class Patient:
    bed: int
    name: str                     # synthetic
    pathway: Pathway
    fit_at: datetime              # when declared medically fit (MFFD)
    departed_at: Optional[datetime] = None
    tasks: list[Task] = field(default_factory=list)


@dataclass
class LedgerEntry:
    actor: Actor
    action: str                   # e.g. "task.update", "approval.granted", "escalation"
    at: datetime
    bed: int
    task_id: Optional[str] = None
    approval_id: Optional[str] = None
    detail: Optional[str] = None


@dataclass
class Blocker:
    bed: int
    task_id: Optional[str]
    summary: str                  # "Margaret is waiting on: TTO dispensing (ETA 11:45). Owner: pharmacist."
    owner_role: Optional[Role]
    eta: Optional[datetime]


class ErrorCode(str, Enum):
    INVALID_TRANSITION = "INVALID_TRANSITION"
    HUMAN_ONLY = "HUMAN_ONLY"
    FORBIDDEN_ROLE = "FORBIDDEN_ROLE"
    DEPENDENCY_UNMET = "DEPENDENCY_UNMET"
    PICKUP_TOO_EARLY = "PICKUP_TOO_EARLY"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"
    NOT_FOUND = "NOT_FOUND"
    VALIDATION = "VALIDATION"


@dataclass
class HomewardError(Exception):
    """Rejected write. Wire shape: {"error": {"code", "message", "details"}} (HTTP 409/422/404)."""
    code: ErrorCode
    message: str
    details: dict = field(default_factory=dict)

    def to_wire(self) -> dict:
        return {"error": {"code": self.code.value, "message": self.message, "details": self.details}}


def can_transition(src: TaskStatus, dst: TaskStatus) -> bool:
    return dst in TRANSITIONS[src]


def is_human_only(kind: TaskKind) -> bool:
    return kind in HUMAN_ONLY_KINDS


def to_wire(obj) -> dict:
    """Dataclass -> JSON-safe dict (enums -> values, datetimes -> ISO-8601)."""
    def conv(v):
        if isinstance(v, Enum):
            return v.value
        if isinstance(v, datetime):
            return v.isoformat()
        if isinstance(v, dict):
            return {k: conv(x) for k, x in v.items()}
        if isinstance(v, (list, tuple)):
            return [conv(x) for x in v]
        return v
    return conv(asdict(obj))
