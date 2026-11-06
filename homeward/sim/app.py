"""Homeward simulator API (P2). Run: python scripts/homeward.py demo  (http://127.0.0.1:8765/docs)

All writes go through the Store, which goes through the engine. Errors use the contract shape
{"error": {"code", "message", "details"}}. Times are ISO-8601; naive times are treated as UTC.
Limitation (documented in README): the `actor` on a write is declared by the caller. In the Switch
deployment the human approver is the person who clicked the approval card.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from pydantic import BaseModel, Field

from homeward import engine as e
from homeward.contracts import (
    CONTRACT_VERSION, Actor, ActorType, ErrorCode, HomewardError, Pathway, Role, TaskKind, TaskStatus, to_wire,
)
from homeward.sim import seed

STATUS = {ErrorCode.NOT_FOUND: 404, ErrorCode.HUMAN_ONLY: 403, ErrorCode.FORBIDDEN_ROLE: 403,
          ErrorCode.VALIDATION: 422}

app = FastAPI(title="Homeward sim", version=CONTRACT_VERSION,
              description="Simulated hospital systems + readiness engine for the Homeward Switch demo. Synthetic data only.")
STATE = {"store": seed.build("margaret"), "scenario": "margaret"}
STATIC = Path(__file__).parent / "static"


def store():
    return STATE["store"]


def utc(t: Optional[datetime]) -> Optional[datetime]:
    if t is None:
        return None
    return t.replace(tzinfo=timezone.utc) if t.tzinfo is None else t.astimezone(timezone.utc)


@app.exception_handler(HomewardError)
async def homeward_error(_req: Request, exc: HomewardError):
    return JSONResponse(exc.to_wire(), status_code=STATUS.get(exc.code, 409))


@app.exception_handler(RequestValidationError)
async def validation_error(_req: Request, exc: RequestValidationError):
    err = HomewardError(ErrorCode.VALIDATION, "request body or parameters are invalid",
                        {"errors": [{"loc": list(x.get("loc", [])), "msg": x.get("msg")} for x in exc.errors()]})
    return JSONResponse(err.to_wire(), status_code=422)


# --- request bodies ----------------------------------------------------------------
class ActorIn(BaseModel):
    id: str = Field(min_length=1)
    role: Role
    type: ActorType = ActorType.HUMAN

    def to_actor(self) -> Actor:
        return Actor(self.id, self.role, self.type)


class ClockIn(BaseModel):
    now: Optional[datetime] = None
    advance_minutes: Optional[int] = Field(default=None, ge=0, le=24 * 60)


class ResetIn(BaseModel):
    scenario: str = "margaret"


class MffdIn(BaseModel):
    pathway: Pathway
    actor: ActorIn
    letter_eta: Optional[datetime] = None


class TaskPatch(BaseModel):
    status: TaskStatus
    actor: ActorIn
    eta: Optional[datetime] = None
    detail: Optional[str] = Field(default=None, max_length=300)  # e.g. "reported by nurse-amy: Sarah told 10:05"


class TtoRequestIn(BaseModel):
    actor: ActorIn
    priority: str = "routine"


class BookingIn(BaseModel):
    slot: datetime
    actor: ActorIn
    vehicle: Optional[str] = None


class ConfirmIn(BaseModel):
    approval_id: str
    approver: ActorIn


class ApproverIn(BaseModel):
    approver: ActorIn


class EventIn(BaseModel):
    type: str
    bed: Optional[int] = None
    at: Optional[datetime] = None
    reason: Optional[str] = None
    minutes: Optional[int] = None
    doctor: Optional[str] = None


def ledger_out(entries):
    return [to_wire(x) for x in entries]


# --- system ------------------------------------------------------------------------
@app.get("/health")
def health():
    return {"ok": True, "contract": CONTRACT_VERSION, "scenario": STATE["scenario"], "now": store().clock.isoformat()}


@app.post("/reset")
def reset(body: ResetIn = ResetIn()):
    try:
        STATE["store"] = seed.build(body.scenario)
    except KeyError:
        raise HomewardError(ErrorCode.NOT_FOUND, f"unknown scenario {body.scenario}", {"known": list(seed.SCENARIOS)})
    STATE["scenario"] = body.scenario
    return health()


@app.get("/clock")
def get_clock():
    return {"now": store().clock.isoformat()}


@app.post("/clock")
def set_clock(body: ClockIn):
    s = store()
    if (body.now is None) == (body.advance_minutes is None):
        raise HomewardError(ErrorCode.VALIDATION, "send exactly one of now or advance_minutes", {})
    target = utc(body.now) if body.now else s.clock + timedelta(minutes=body.advance_minutes)
    with s.lock:
        fired = s.advance_to(target)
    return {"now": s.clock.isoformat(), "events": ledger_out(fired)}


# --- patients and plans ----------------------------------------------------------------
@app.get("/patients")
def list_patients():
    s = store()
    out = []
    for bed in sorted(s.inpatients):
        row = s.patient_view(bed)
        if row["declared_fit"]:
            row["blocker"] = e.blocker(s.plans[bed], s.clock).summary
        out.append(row)
    return out


@app.get("/patients/{bed}")
def get_patient(bed: int):
    s = store()
    row = s.patient_view(bed)
    row["eligibility"] = s.eligibility(bed)
    if row["declared_fit"]:
        row["plan"] = s.plan_view(bed)["tasks"]
    return row


@app.post("/patients/{bed}/mffd")
def declare_mffd(bed: int, body: MffdIn):
    s = store()
    with s.lock:
        s.declare_mffd(bed, body.pathway, body.actor.to_actor(), utc(body.letter_eta))
    return s.plan_view(bed)


@app.get("/patients/{bed}/plan")
def get_plan(bed: int):
    return store().plan_view(bed)


@app.get("/patients/{bed}/blocker")
def get_blocker(bed: int):
    return store().blocker_view(bed)


@app.get("/patients/{bed}/handover", response_class=PlainTextResponse)
def get_handover(bed: int):
    s = store()
    return e.handover_summary(s.plan(bed), s.clock)


@app.patch("/patients/{bed}/tasks/{task_id}")
def patch_task(bed: int, task_id: str, body: TaskPatch):
    s = store()
    with s.lock:
        entries = s.update_task(bed, task_id, body.status, body.actor.to_actor(), utc(body.eta), body.detail)
    return {"task": next(t for t in s.plan_view(bed)["tasks"] if t["id"] == task_id), "ledger": ledger_out(entries)}


@app.post("/patients/{bed}/depart")
def depart(bed: int, body: ApproverIn):
    s = store()
    with s.lock:
        entry = e.depart(s.plan(bed), body.approver.to_actor(), s.clock)
        s.ledger.append(entry)
    return {"departed_at": s.clock.isoformat(), "cost": e.cost(s.plan(bed), s.clock)}


@app.get("/patients/{bed}/ledger")
def get_ledger(bed: int):
    s = store()
    s.inpatient(bed)
    return s.ledger_view(bed)


# --- pharmacy ----------------------------------------------------------------------------
@app.get("/patients/{bed}/tto")
def get_tto(bed: int):
    return store().tto_view(bed)


@app.post("/patients/{bed}/tto/request")
def request_tto(bed: int, body: TtoRequestIn):
    s = store()
    with s.lock:
        s.request_tto(bed, body.actor.to_actor(), body.priority)
    return s.tto_view(bed)


# --- transport ------------------------------------------------------------------------------
@app.get("/patients/{bed}/transport/eligibility")
def get_eligibility(bed: int):
    s = store()
    out = s.eligibility(bed)
    if bed in s.plans:
        p = s.plans[bed]
        tto, letter = e.find_task(p, TaskKind.TTO_DISPENSE), e.find_task(p, TaskKind.LETTER_SIGNED)
        etas = [x for x in (tto.eta, letter.eta) if x]
        out["earliest_pickup"] = (max(etas) + timedelta(minutes=e.PICKUP_BUFFER_MIN)).isoformat() if etas else None
    return out


@app.get("/transport/slots")
def get_slots(vehicle: str, after: Optional[datetime] = None):
    return {"vehicle": vehicle, "slots": store().slots(vehicle, utc(after))}


@app.post("/patients/{bed}/transport/bookings")
def request_booking(bed: int, body: BookingIn):
    s = store()
    with s.lock:
        b = s.request_booking(bed, utc(body.slot), body.actor.to_actor(), body.vehicle)
    return {**s.booking_view(b), "next": f"a nurse must approve: POST /patients/{bed}/transport/bookings/{b.id}/confirm"}


@app.post("/patients/{bed}/transport/bookings/{booking_id}/confirm")
def confirm_booking(bed: int, booking_id: str, body: ConfirmIn):
    s = store()
    with s.lock:
        b = s.confirm_booking(bed, booking_id, body.approval_id, body.approver.to_actor())
    return s.booking_view(b)


@app.post("/patients/{bed}/transport/bookings/{booking_id}/decline")
def decline_booking(bed: int, booking_id: str, body: ApproverIn):
    s = store()
    with s.lock:
        b = s.decline_booking(bed, booking_id, body.approver.to_actor())
    return s.booking_view(b)


# --- board and events ------------------------------------------------------------------
@app.get("/board/ward")
def board_ward():
    return store().board()


@app.get("/board")
def board_page():
    page = STATIC / "board.html"
    if not page.exists():
        raise HomewardError(ErrorCode.NOT_FOUND, "board page arrives in P5; JSON is at /board/ward", {})
    return FileResponse(page)


@app.post("/events")
def post_event(body: EventIn):
    s = store()
    with s.lock:
        fired = s.apply_event(body.type, {"bed": body.bed, "at": utc(body.at), "reason": body.reason,
                                          "minutes": body.minutes, "doctor": body.doctor})
    return {"now": s.clock.isoformat(), "scheduled": bool(body.at and utc(body.at) > s.clock),
            "events": ledger_out(fired)}
