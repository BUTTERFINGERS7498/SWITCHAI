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

## REST API (`homeward/sim/app.py`, built in P2; port 8765; OpenAPI at `/docs`)
Errors: `{"error":{"code","message","details"}}`; 404 NOT_FOUND, 403 HUMAN_ONLY/FORBIDDEN_ROLE, 422 VALIDATION,
409 INVALID_TRANSITION/DEPENDENCY_UNMET/PICKUP_TOO_EARLY/APPROVAL_REQUIRED. Times ISO-8601 (naive = UTC).
Actors: `{"id","role","type": human|agent|system}`. Agents use role `coordinator` and put the human source in `detail`.

| Method + path | Purpose | Who |
|---|---|---|
| `GET /health`, `POST /reset {"scenario"}` | status / reseed ward 7 at 10:00 | runner |
| `GET /clock`, `POST /clock {"now"} or {"advance_minutes"}` | scenario clock; fires due events, nudges | runner |
| `GET /patients`, `GET /patients/{bed}` | ward list with blocker / one patient + eligibility + plan | agents |
| `POST /patients/{bed}/mffd {"pathway","actor","letter_eta?"}` | declare medically fit (doctor only) | human |
| `GET /patients/{bed}/plan` · `/blocker` · `/handover` · `/ledger` | tasks / blocker+cost+overdue / shift handover text / audit | agents |
| `PATCH /patients/{bed}/tasks/{id} {"status","actor","eta?","detail?"}` | validated transition (not TTO, not transport completion) | agents/humans |
| `GET /patients/{bed}/tto`, `POST /patients/{bed}/tto/request {"actor","priority"}` | pharmacy status / send TTO request | pharmacy agent |
| `GET /patients/{bed}/transport/eligibility` | vehicle + earliest pickup | transport agent |
| `GET /transport/slots?vehicle=&after=` | free 15-min slots 11:00-18:00 | transport agent |
| `POST /patients/{bed}/transport/bookings {"slot","actor","vehicle?"}` | request -> AWAITING_APPROVAL + `approval_id` | transport agent |
| `POST .../bookings/{id}/confirm {"approval_id","approver"}` | nurse approval -> IN_PROGRESS, pickup scheduled | human (nurse) |
| `POST .../bookings/{id}/decline {"approver"}` | decline -> READY, slot freed | human |
| `POST /patients/{bed}/depart {"approver"}` | manual departure (normally crew at pickup +10 min) | human |
| `GET /board/ward`, `GET /board` | board JSON / board page (P5) | board |
| `POST /events {"type","bed","at?",...}` | `transport_cancelled`, `letter_signed`, `tto_delayed`; `at` schedules it | runner |

Simulated systems act on the clock: pharmacy verifies (40 min) and dispenses (45 min) after a request; the crew
collects at the slot (or leaves if the patient isn't ready) and the patient departs 10 min later; doctors sign
letters in the "EPR" via `letter_signed`. Agents never act as those people.

## Agent tools (P3)
Agents use two stdlib-only commands from the repo folder (their Switch working directory):
```
python scripts/homeward.py read patients/12/blocker            # GET only; auto-allowed
python scripts/homeward.py write POST patients/12/tto/request '<json>'   # changes state; approval card
```
Output: an optional one-line human summary (blocker line, `REJECTED <code>: <message>`, booking awaiting approval),
then the JSON on the last line. Exit codes: 0 ok, 1 rejected by Homeward, 2 usage, 3 sim unreachable.
Paths are written without a leading `/`: Git Bash (the agents' shell on Windows) rewrites `/x` into
`C:/Program Files/Git/x`; the CLI also undoes that rewrite. Base URL from `HOMEWARD_URL` (default `http://127.0.0.1:8765`). Approval: Claude Code project rule in
`.claude/settings.json`: `allow` `Bash(python scripts/homeward.py read:*)`, `ask` `Bash(python scripts/homeward.py write:*)`.
MCP wrapper dropped (cut list item 1); the CLI is the tool surface.

## Switch spike (gating checks, run by a human; fallbacks in DECISIONS.md)
1 server up · 2 Claude Code answers an @role in one room · 3 room document write then read-back ·
4 approval card (+ who can approve) · 5 our tools callable from an agent session.

## Ownership
001 Claude-S contract/bootstrap · 002 Claude-R engine · 003 Claude-S sim · 004 Claude-R tools ·
005 Claude-S roles + Switch rooms · 006 Claude-R board · 007 Claude-S scenario e2e · 008 Claude-R README/CI.
