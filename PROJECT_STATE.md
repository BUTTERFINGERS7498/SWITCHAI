# PROJECT_STATE

Updated: 2026-11-07 (P3 done)

## Requirements
Flip the Switch hackathon, Track 01. Homeward: agents + humans in Switch rooms clear non-clinical discharge
blockers. Needs public repo, demo video (~2:50), README explaining Switch use. Deadline 7 Nov 23:59 IST (target 22:00).
Hard exclusions: clinical decisions/documents, real data, EPR integration, multi-ward, auth, mobile.

## Architecture
See `docs/ARCHITECTURE.md`. Contract: `homeward/contracts.py` v1.0.0.

## Decisions
See `docs/DECISIONS.md`.

## Task ownership and status (solo since 2026-11-07; plan: docs/IMPLEMENTATION_PLAN.md)
| Phase | Scope | Status |
|---|---|---|
| P0 | Switch spike | done, all 5 checks pass (docs/SPIKE.md) |
| P1 | readiness engine `homeward/engine.py` | done (32 tests) |
| P2 | simulator `homeward/sim/` | done (19 API tests) |
| P3 | agent CLI `homeward.py read/write` | done (7 end-to-end CLI tests) |
| P4 | Switch rooms, roles, approvals | files done (`switch/`); Console/Slack setup in progress |
| P5 | board page | done (`/board`) |
| P6 | scenario runner | pending |
| P7-P9 | README, video, submit | pending |

## Completed
- TASK-001 bootstrap + contract (v1.1.0 now). P1 engine. P2 sim. 76 tests pass: `python scripts/homeward.py test`.

## Pending / issues
- Switch spike not yet run (needs human at Console). Not verified that Switch runs on either machine.
- Slack app install for Switch needs workspace admin approval (Sarvagya to confirm).
- Repo is private; must be made public before submission.

## Current next task
P4: role instruction files in `switch/`, rooms #ward-7 / #discharge-bed-12 / #pharmacy / #transport-desk, agents discharge-lead / pharmacy-liaison / transport, approval card re-test.
