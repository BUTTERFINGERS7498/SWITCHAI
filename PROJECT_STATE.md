# PROJECT_STATE

Updated: 2026-11-06 by Claude-S (TASK-001)

## Requirements
Flip the Switch hackathon, Track 01. Homeward: agents + humans in Switch rooms clear non-clinical discharge
blockers. Needs public repo, demo video (~2:50), README explaining Switch use. Deadline 7 Nov 23:59 IST (target 22:00).
Hard exclusions: clinical decisions/documents, real data, EPR integration, multi-ward, auth, mobile.

## Architecture
See `docs/ARCHITECTURE.md`. Contract: `homeward/contracts.py` v1.0.0.

## Decisions
See `docs/DECISIONS.md`.

## Task ownership and status
| Task | Owner | Scope | Status |
|---|---|---|---|
| 001 | Claude-S | bootstrap, contract, docs, entrypoint | in review |
| 002 | Claude-R | readiness engine + pytest | next |
| 003 | Claude-S | sim FastAPI + SQLite | pending |
| 004 | Claude-R | homeward-mcp tools over REST | pending |
| 005 | Claude-S | role instructions + Switch rooms | pending |
| 006 | Claude-R | ward board | pending |
| 007 | Claude-S | scenario runner + Margaret e2e | pending |
| 008 | Claude-R | README, diagram, CI, fresh-clone | pending |

## Completed
TASK-001 (pending review): contract types, transition table, errors, REST+tool contract, entrypoint, tests (9 pass).

## Pending / issues
- Switch spike not yet run (needs human at Console). Not verified that Switch runs on either machine.
- Slack app install for Switch needs workspace admin approval (Sarvagya to confirm).
- Repo is private; must be made public before submission.

## Current next task
TASK-002 (Claude-R): readiness engine as pure functions + pytest, against `homeward/contracts.py`.
