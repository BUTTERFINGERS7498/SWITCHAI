# Live end-to-end run in Slack (2026-11-07, ~04:10-04:40 IST)

Humans: Sarvagya as nurse-amy in Slack. Agents: discharge-lead (@lead), pharmacy-liaison (@meds),
transport-liaison (@transport), Claude Code via Switch, working directory = repo. Hospital events driven from the
terminal (EPR MFFD and letter, clock, provider cancellation). Sim on pre-P6 code (TTO 40+45 min).

| Sim time | What happened | Who | Approval |
|---|---|---|---|
| 10:00 | MFFD bed 12, pathway P0 (EPR) | dr-raj (hospital system) | — |
| 10:00 | TTO request sent: @lead handed off to @meds without being asked | pharmacy-liaison (agent) | Switch card, allowed by Sarvagya |
| 10:20 | Wheelchair pickup 11:45 proposed, booked and confirmed in one call | transport-liaison (agent) | A-2, nurse-amy |
| 10:20 | Family informed, belongings packed: "reported by nurse-amy: ..." | discharge-lead (agent) | Switch cards |
| 11:00 | Letter signed in EPR | dr-raj (hospital system) | — |
| 11:20 | Provider cancelled 11:45 (vehicle breakdown); board BLOCKED | transport-system | — |
| 11:20 | Rebooked 12:00 after one prompt | transport-liaison (agent) | A-3, nurse-amy |
| — | Shift handover asked of @lead (step 6; answer not separately confirmed) | discharge-lead | — |
| 12:00 / 12:10 | Crew collected; departed 12:10 | crew (hospital system) | — |
| after 12:10 | "@lead is Margaret home?" answered correctly (step 7, confirmed by Sarvagya) | discharge-lead | — |

Result: home 12:10 vs 19:10 baseline (7.0 bed-hours freed). 2 human approvals in the hospital ledger, 6 agent
writes, 0 clinical actions by agents.

Findings
- Agent-to-agent hand-off works under "Me and my agents".
- Approval cards appear for every `homeward.py write`; reads run freely.
- Old code escalated instantly on cancellation ("80 min since ready"); fixed in P6 (D34) before this run was repeated.
- With P6 timings (50+55 min) the same flow gives the dossier story: 12:15 -> cancelled -> 12:30 -> home 12:40.

Pending from this run: boundary checks (letter, TTO status, MFFD for bed 15, booking for unfit bed 15).
