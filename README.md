# Homeward

> Dashboards show who's stuck. Homeward gets them home.

Homeward puts accountable AI agents into a Switch team-chat room per patient to clear the
**non-clinical** blockers that keep medically fit patients in hospital beds: medicines, transport, paperwork, handover.
Agents never make clinical decisions. All data is synthetic.

*(README skeleton from TASK-001; the full README, Switch feature table, GIFs and the unplug test land in TASK-008.)*

## Run
```
python scripts/homeward.py test        # works today
python scripts/homeward.py setup|demo|scenario   # coming in later tasks
```
`make <cmd>` is a thin wrapper for Mac/Linux.

## Glossary
MFFD medically fit for discharge · TTO "to take out" (discharge medicines) · Pathway 0-3 (home / home with
support / rehab bed / care home) · Bed-day one bed for one day (£562) · EPR electronic patient record.

## Docs
`docs/ARCHITECTURE.md` · `docs/DECISIONS.md` · `PROJECT_STATE.md`
