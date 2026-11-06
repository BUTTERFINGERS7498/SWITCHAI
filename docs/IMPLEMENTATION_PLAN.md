# Homeward: solo implementation plan

Written 2026-11-07 01:20 IST. Builder: Sarvagya plus Claude (solo; Raghav's agent no longer owns tasks).
Deadline 23:59 IST, **internal submit target 22:00 IST**. About 20.5 h of clock time and about 18 h of work,
so there is room for **one sleep block of ~3 h**, not more.

The contract in `homeward/contracts.py` (v1.0.0) and `docs/ARCHITECTURE.md` stay the source of truth.
Changes below are listed in "Decision changes for solo"; each one gets a row in `docs/DECISIONS.md`.

---

## 1. What we must show (judging-driven)

| Criterion (weight) | What we need on screen |
|---|---|
| Use of Switch (30%) | Room per patient, 3 role agents, approval cards on every write, checklist as a room document, addressing policy, unplug table in README |
| Technical execution (25%) | `python scripts/homeward.py setup && ... demo` works on a fresh clone; engine tests pass; deterministic scenario |
| Creativity & impact (25%) | Margaret story: 19:10 to 12:40, 6.5 bed-hours, £ meter, non-clinical guarantee enforced in code |
| Presentation (20%) | 2:30–2:50 video, scannable README, glossary |

**MVP (must exist by Gate G2):** engine + sim + agent tool access + 3 agents in Switch with approvals +
one scenario with the transport-cancel curveball + shift-handover Q&A + board showing blocker and £ meter.

**Cut entirely (solo):** Codex agent, `@care-handover`, `@ward-clerk` custom agent, "expected fit tomorrow"
pre-staging, multiple patients in the demo (seed 4, demo 1), CI beyond one GitHub Actions pytest job.

---

## 2. Decision changes for solo (record in DECISIONS.md)

| # | Change | Why |
|---|---|---|
| D13 | Sim state is **in-memory**, with `POST /reset` and a JSON snapshot; no SQLite | Deterministic resets, about 1 h saved, nothing to migrate |
| D14 | Board is **one static HTML page served by FastAPI at `/board`** (vanilla JS polling `/board/ward`), not React | No Node build step for judges; about 2 h saved |
| D15 | Agent tool access = **CLI first** (`homeward.py call ...`), split into read and write commands so Switch's allow-list can auto-allow reads and require approval for writes. MCP wrapper only if the spike shows it is trivial | Switch approval cards attach to tool or command permissions; separate commands make the "every write is approved" story real |
| D16 | Rooms are **pre-created by `setup`**; `@discharge-lead` "activates" the patient room | Removes the spike's riskiest unknown (agent-created rooms) |
| D17 | One FastAPI process serves the API and the board; port 8765 | One thing to start |

---

## 3. Phases, gates and timeline

Times assume you start now (01:30) and take one ~3 h sleep after Gate G1. If anything slips, apply the cut
order in §6, not a later submission.

| # | Phase | Est. | Target end (IST) | Gate |
|---|---|---|---|---|
| P0 | Housekeeping + **Switch spike** | 2.0 h | 03:30 | **G0: Switch path chosen** |
| P1 | Readiness engine + tests | 2.5 h | 06:00 | **G1: engine green** |
| — | Sleep | 3.0 h | 09:00 | |
| P2 | Sim API (FastAPI, in-memory) + API tests | 2.5 h | 11:30 | |
| P3 | Agent tool CLI (`call`, read/write split) | 1.0 h | 12:30 | |
| P4 | Switch rooms, role instructions, approvals, room docs | 2.5 h | 15:00 | **G2: MVP live in Switch** |
| P5 | Board page | 1.0 h | 16:00 | |
| P6 | Scenario runner + Margaret end-to-end + 3 rehearsal runs | 1.5 h | 17:30 | **G3: feature freeze** |
| P7 | README, diagram, unplug table, GIFs | 1.5 h | 19:00 | |
| P8 | Record + edit video | 1.5 h | 20:30 | |
| P9 | Fresh-clone test, repo public, submit | 1.0 h | 21:30 | **G4: submitted** |
| | Buffer | 0.5 h | 22:00 | |

---

## 4. Phase detail

### P0 — Housekeeping + Switch spike (2 h)
Housekeeping (15 min):
- Merge PR #1 into `main` (it's yours now; no second reviewer).
- GitHub default branch is currently `task-001-bootstrap` (it was pushed first): set it to `main`.
- Post a short note in Slack telling Raghav's Claude that the even tasks are withdrawn and Sarvagya is building solo, so it doesn't push to the repo.
- Work on short-lived branches or straight on `main`, with a commit per phase; push at each gate.

Spike: install Switch Console, connect it to the Team RE:SET Slack (app already installed) and run these checks.
Write the results into `docs/SPIKE.md`.

| # | Check | Pass looks like | Fallback if it fails |
|---|---|---|---|
| 1 | Server + Console up on this Windows machine | Console shows server healthy | Run on Raghav's Mac (ask), or Switch's Docker image |
| 2 | Claude Code session answers `@discharge-lead` in a channel | Reply in thread | Address the agent by name instead of by role; keep role names in instructions |
| 3 | Room document write then read-back | Same content returned | Checklist lives in sim; agent posts it as a pinned message |
| 4 | Approval card on a write command, while a read command is auto-allowed | Card with Allow once / Decline; who approved is recorded | Engine requires `approver` and checks it against a role roster; the card is still shown |
| 5 | Agent session can run `python scripts/homeward.py call GET /clock` | JSON comes back in chat | Agent uses `curl` to the same REST API |

**G0 exit:** for each check, a pass or the chosen fallback is written in `docs/SPIKE.md`. If check 1 or 2 fails
and has no fallback by 04:00, stop and decide whether to continue on Switch (it's mandatory) or debug only that.

### P1 — Readiness engine (2.5 h) → `homeward/engine.py`, `tests/test_engine.py`
Pure functions. No I/O, no wall clock; every function takes `now`.

| Function | Behaviour |
|---|---|
| `build_plan(bed, name, pathway, fit_at) -> Patient` | Tasks from `PATHWAY_TASKS`, ids `t1..tn`, deps resolved from `DEPENDS_ON`, `human_only` from `HUMAN_ONLY_KINDS`, targets from `TARGET_MINUTES`; tasks with no deps start READY with `ready_at=fit_at` |
| `apply_transition(p, task_id, dst, actor, now, eta=None) -> LedgerEntry` | Validates `TRANSITIONS`, deps DONE before IN_PROGRESS/DONE, `HUMAN_ONLY` (agent or system completing a human-only task) and `FORBIDDEN_ROLE` (a human without the owner role completing a task, except nurse as override for non-clinical tasks). Sets ETA. Promotes dependants to READY |
| `check_pickup(slot, tto_eta, letter_eta)` | Raises `PICKUP_TOO_EARLY` unless `slot >= max(etas) + 20 min` |
| `blocker(p, now) -> Blocker` | Not-DONE task with the latest ETA (unknown ETA counts as latest); summary text "Margaret is waiting on: TTO dispensing (ETA 11:45). Owner: pharmacist." |
| `due_actions(p, now) -> list[(task_id, "nudge"/"escalate")]` | Per target: a nudge at target, a nudge at 1.5× target, escalate to `bed_manager` after `NUDGES_BEFORE_ESCALATION`; idempotent via `task.nudges` |
| `cost(p, now) -> {hours, gbp}` | `BED_HOUR_GBP` × hours from `fit_at` to `departed_at or now` |
| `depart(p, actor, now)` | Allowed only when all tasks are DONE; sets `departed_at` |
| `handover_summary(p, now) -> str` | I-PASS-style: status · open tasks · owner · next deadline |

Tests (about 20): every transition-table edge, an agent completing the letter → `HUMAN_ONLY`, a dependency
not met, the pickup rule boundary (exactly +20 min passes, +19 fails), the blocker picks the latest ETA,
nudge → nudge → escalate exactly once, cost at known times, departure blocked until all DONE, P0 vs P1 task counts.
**G1 exit:** `python scripts/homeward.py test` all green.

### P2 — Sim API (2.5 h) → `homeward/sim/app.py`, `state.py`, `seed.py`, `tests/test_api.py`
- Implements the REST table in ARCHITECTURE.md exactly, plus `POST /reset {"scenario": "margaret"}`.
- `state.py`: in-memory `Store` (patients, clock, ledger, bookings, approvals) with every write going through the engine.
- `seed.py`: 4 synthetic patients; Margaret Jones, 82, bed 12, P1, fit 10:00. Pharmacy and transport behaviour is
  scripted: TTO verify takes 40 min, dispense 45 min; transport slots every 15 min from 11:00; eligibility: Margaret needs a wheelchair vehicle.
- Bookings: `POST .../bookings` → task AWAITING_APPROVAL with an `approval_id`; `confirm` requires `approver` with role nurse → DONE plus a ledger entry.
- Events: `transport_cancelled` → transport task BLOCKED; agent rebooks (BLOCKED→READY→AWAITING_APPROVAL).
- `HomewardError` → JSON error with the mapped HTTP status (a FastAPI exception handler).
- Tests with FastAPI `TestClient`: happy path, curveball, human-only rejected over HTTP, clock advance.
- `python scripts/homeward.py setup` creates `.venv` and installs `requirements.txt` (fastapi, uvicorn, httpx, pytest).
  `demo` starts uvicorn on :8765.

### P3 — Agent tool CLI (1 h) → `scripts/homeward.py`
- `homeward.py read <path>` (GET only) and `homeward.py write <METHOD> <path> '<json>'`: two commands, so the
  Switch allow-list can auto-allow `read` and require an approval card for `write`.
- Short aliases documented for agents: `read /patients/12/blocker`, `write POST /patients/12/transport/bookings '{"slot":"...","actor":{...}}'`.
- Output: compact JSON, plus a one-line human summary for blocker and handover.

### P4 — Switch setup (2.5 h) → `switch/` folder
- `switch/rooms.md`: `#ward-7` (hub), `#discharge-bed-12` (patient), `#pharmacy`, `#transport-desk`. Created in Slack by
  hand (or the setup script, if Switch supports it), then linked in Switch.
- `switch/roles/discharge-lead.md`, `pharmacy-liaison.md`, `transport.md`: role instructions (non-clinical boundary,
  reply in threads, use only `homeward.py read/write`, never complete human-only tasks, always cite the blocker line).
- `switch/room-instructions.md`: the shared briefing for the patient room.
- Exclusive role `@discharge-lead`; addressing policy: only the nurse can instruct `@transport`.
- The checklist room document is regenerated by `@discharge-lead` from `GET /patients/12/plan` after each change.
- **G2 exit:** in Slack, the doctor types the MFFD line → plan doc appears → pharmacy request → transport booking
  with an approval card the nurse clicks → board turns green. Runs end to end twice.

### P5 — Board (1 h) → `homeward/sim/static/board.html`
Beds, current blocker line, per-task status chips, timers against targets, £ meter, last 8 ledger entries.
Polls every 2 s. Amber when a task is BLOCKED or past target, green when all are DONE.

### P6 — Scenario runner (1.5 h) → `homeward.py scenario margaret`
- Resets the sim, sets the clock to 10:00, and steps a scripted timeline (advance clock, inject `transport_cancelled` at
  11:20, advance to departure). The human actions in Slack (MFFD line, approvals) are done live; the runner only
  drives the clock and events, and prints the before/after: departure time, bed-hours freed, approvals count.
- `--auto` mode also simulates the human approvals via the API, so judges can see the whole flow without Slack.
- **G3 exit:** 3 clean rehearsal runs. Freeze features.

### P7–P9 — Presentation and submit
- README: hook, problem numbers, architecture diagram, **Switch feature → where used → what breaks without it**
  table (the unplug test), safety and non-clinical section, limitations (the approver identity comes from the agent's
  call; production would use Switch's recorded approver), how to run, glossary.
- Video script: the dossier's 2:50 storyboard (§01 demo script). Record the board and Slack side by side.
- Fresh-clone test in a new folder: `setup`, `test`, `demo`, `scenario margaret --auto`. Make the repo **public**.
  Submit on WeMakeDevs with repo + video. Optional blog post only if time is left.

---

## 5. Repo layout at the end
```
homeward/contracts.py  engine.py  sim/{app.py,state.py,seed.py,static/board.html}
scripts/homeward.py    switch/{rooms.md,room-instructions.md,roles/*.md}
tests/{test_contracts.py,test_engine.py,test_api.py}
docs/{ARCHITECTURE.md,DECISIONS.md,SPIKE.md,IMPLEMENTATION_PLAN.md}  README.md  PROJECT_STATE.md
requirements.txt  Makefile  .github/workflows/test.yml
```

## 6. Cut order (apply top-down when behind schedule)
1. MCP wrapper (already optional)
2. Board timers/ledger panel → keep only the blocker line + £ meter
3. Addressing policy demo (mention it in the README instead)
4. `--auto` scenario mode
5. GIFs in the README (the video covers it)
6. Shift-handover Q&A as a separate beat (fold it into the final room message)

**Never cut:** approval card on transport booking, human-only enforcement, room per patient, fresh-clone test, video.

## 7. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Switch won't install or connect on Windows | Medium | Spike first (P0); Docker or Raghav's Mac as host |
| Approval cards can't distinguish read and write commands | Medium | D15 read/write split; else engine role roster (D11) |
| LLM agents behave differently between takes | High | Engine owns outcomes; the scenario runner drives the clock; record 3 takes |
| Solo fatigue causes late bugs | High | Feature freeze at G3; no new features after 17:30 |
| Repo left private at submission | Low | Checklist item in P9 |

## 8. Done means
- [ ] `python scripts/homeward.py test` green (contracts + engine + API)
- [ ] Margaret runs end to end in Slack via Switch with at least one approval card
- [ ] Board shows blocker, £ meter and a green finish
- [ ] README has the unplug table and how-to-run; video ≤ 3:00
- [ ] Fresh clone works; repo public; submitted before 22:00 IST
