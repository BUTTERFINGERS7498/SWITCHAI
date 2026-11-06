# Homeward architecture (contract v1.0.0)

Status: proposed in TASK-001, frozen once Claude-R approves the PR. Types live in `homeward/contracts.py`.

## Layers
```
People (Slack)  ->  Switch (rooms, roles, approvals, room docs, addressing)
                      -> agent sessions: @discharge-lead, @pharmacy-liaison, @transport
                          -> tools (REST primary; MCP wrapper over the same REST, TASK-004)
                              -> homeward-sim (FastAPI + SQLite)  [TASK-003]
                                  -> readiness engine (pure functions) [TASK-002]
                              -> ward board (React, polls sim) [TASK-006]
```
- The **engine owns all state transitions**. Agents chase and propose; every write is validated.
- **Non-clinical guarantee in code:** `HUMAN_ONLY_KINDS` (letter signing) can only be completed by a
  `human` actor with the owner role. Agent attempts return `HUMAN_ONLY`.
- **Time is an input.** Every engine function takes `now`. Only the sim owns the scenario clock.
- Stack: Python 3.12+ (stdlib contract + engine; FastAPI/SQLite in sim), React board. $0, local, self-hosted.
- Entrypoint: `python scripts/homeward.py <setup|demo|scenario|test>`; Makefile is a thin wrapper.

## Engine rules (`homeward/engine.py`, built in P1)
API: `build_plan`, `apply_transition` (returns ledger entries), `check_pickup`, `blocker`, `tick` (nudges and
escalations, idempotent), `overdue`, `cost`, `can_depart`, `depart`, `handover_summary`.
- Tasks per pathway: `PATHWAY_TASKS`. Dependencies: `DEPENDS_ON`. Owners: `OWNER_ROLE`.
- Status changes only via `TRANSITIONS`. Each change appends a `LedgerEntry`.
- Pickup rule: `pickup >= max(tto_ready_eta, letter_eta) + PICKUP_BUFFER_MIN` else `PICKUP_TOO_EARLY`.
- Targets: `TARGET_MINUTES`; after `NUDGES_BEFORE_ESCALATION` nudges, escalate to `bed_manager` (ledger entry).
- Blocker = the unfinished task on the critical path (latest ETA among not-DONE tasks).
- Cost: `BED_HOUR_GBP` x hours since `fit_at` (until `departed_at`).
- Departure is allowed only when every task is DONE, and only a human can confirm it.
- A task in AWAITING_APPROVAL can only be completed by a HUMAN (`APPROVAL_REQUIRED`), so agents cannot self-approve.
- Humans may complete tasks they own; a nurse may also complete any non-clinical task (ward override).
  Other roles get `FORBIDDEN_ROLE`. Agents may complete non-clinical tasks that need no approval.
- Nudges at 1x and 1.5x the target, escalation to bed_manager at 2x; BLOCKED -> READY restarts the clock.

## REST API (TASK-003 implements; all bodies JSON; times ISO-8601 UTC; bed = int)
Errors: `{"error":{"code","message","details"}}`; 404 NOT_FOUND, 409 INVALID_TRANSITION/DEPENDENCY_UNMET/
PICKUP_TOO_EARLY/APPROVAL_REQUIRED, 403 HUMAN_ONLY/FORBIDDEN_ROLE, 422 VALIDATION.

| Method + path | Purpose | Write? |
|---|---|---|
| `GET /clock` / `POST /clock {"now"}` or `{"advance_minutes"}` | scenario clock | write |
| `GET /patients` / `GET /patients/{bed}` | list / get (with tasks) | read |
| `POST /patients/{bed}/mffd {"pathway","actor"}` | declare MFFD, build plan | write |
| `GET /patients/{bed}/plan` | tasks + statuses + ETAs | read |
| `GET /patients/{bed}/blocker` | current `Blocker` + cost so far | read |
| `PATCH /patients/{bed}/tasks/{task_id} {"status","actor","eta?"}` | validated transition | write |
| `GET /patients/{bed}/tto` | TTO status + ready ETA | read |
| `GET /patients/{bed}/transport/eligibility` | vehicle/mobility rules | read |
| `GET /transport/slots?vehicle=&after=` | available slots | read |
| `POST /patients/{bed}/transport/bookings {"slot","actor"}` | request booking -> returns `approval_id`, task AWAITING_APPROVAL | write |
| `POST /patients/{bed}/transport/bookings/{id}/confirm {"approval_id","approver"}` | human-approved confirm | write |
| `GET /patients/{bed}/ledger` | approvals + actions | read |
| `GET /board/ward` | board snapshot (blockers, timers, cost, ledger tail) | read |
| `POST /events {"type","bed","at?"}` | scenario injection, e.g. `transport_cancelled` | write |

Tool names (TASK-004) map 1:1: `hospital.get_patient`, `plan.get`, `plan.blocker`, `pharmacy.get_tto`,
`transport.eligibility`, `transport.slots`, `transport.request_booking`, `transport.confirm`,
`plan.update_task`, `board.ward`. Fallback if MCP is not visible to agents:
`python scripts/homeward.py call <METHOD> <path> [json]` via an allow-listed command.

## Switch spike (gating checks, run by a human; fallbacks in DECISIONS.md)
1 server up · 2 Claude Code answers an @role in one room · 3 room document write then read-back ·
4 approval card (+ who can approve) · 5 our tools callable from an agent session.

## Ownership
001 Claude-S contract/bootstrap · 002 Claude-R engine · 003 Claude-S sim · 004 Claude-R tools ·
005 Claude-S roles + Switch rooms · 006 Claude-R board · 007 Claude-S scenario e2e · 008 Claude-R README/CI.
