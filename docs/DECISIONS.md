# Decisions

| # | Decision | Why | Status |
|---|---|---|---|
| D1 | Homeward = non-clinical NHS discharge logistics; all data synthetic | Scope/safety; judges' trust | agreed |
| D2 | Two Claude agents alternate tasks: Claude-S odd, Claude-R even; one PR per task from `task-<n>-<slug>`, other agent reviews | Avoid scope collisions | agreed |
| D3 | Python for contract/engine/sim; React board | One language, MCP SDK, fast | agreed |
| D4 | Deterministic engine owns state; agents propose via validated tools | Reproducible demo, pytest, non-clinical guarantee | agreed |
| D5 | REST is the primary contract; MCP is a wrapper | If MCP is invisible to agents, REST via allow-listed command still works | agreed (Claude-R) |
| D6 | Engine before sim (TASK-002 engine, TASK-003 sim) | Sim state endpoints need the engine | agreed |
| D7 | `now` is an explicit input; sim owns the single scenario clock | Deterministic `scenario S=margaret` | agreed |
| D8 | Cross-platform entrypoint `scripts/homeward.py`; Makefile is a thin wrapper | Windows has no `make` | agreed |
| D9 | Slack (Team RE:SET) as chat surface; needs Slack app install approved by workspace admin | Fewer setup risks than Mattermost | agreed, admin approval OPEN |
| D10 | Demo host = first machine to pass the 5-check spike | Don't assume the Mac | agreed |
| D11 | Spike fallbacks: no room creation -> pre-create rooms; no per-person approvals -> engine checks role roster; MCP invisible -> REST via allow-listed command | Keep demo alive | proposed |
| D12 | Contract types are stdlib dataclasses (no pydantic) so the engine stays dependency-free | Simplicity | proposed in TASK-001 |
| D13 | Sim state in memory with `POST /reset`; no SQLite | Deterministic resets; saves time solo | agreed (solo plan) |
| D14 | Board is one static HTML page served by FastAPI at `/board` | No Node build for judges | agreed (solo plan) |
| D15 | Agent tools are CLI `homeward.py read`/`write`; Claude Code `ask` rule forces approval on `write` | Auto mode ran commands without a card in the spike | agreed; `.claude/settings.json` must be created by Sarvagya |
| D16 | Patient rooms pre-created; `@discharge-lead` activates them | Agent room creation not needed | agreed (solo plan) |
| D17 | One FastAPI process serves API and board on :8765 | One thing to start | agreed (solo plan) |
| D18 | Engine: AWAITING_APPROVAL -> DONE and departure require a HUMAN actor; nurse may complete any non-clinical task | Approvals enforced in code, not just in chat | P1 |
| D19 | Demo times are UTC (UK time in November) | No timezone conversion needed | P1 |
| D20 | Contract 1.1.0: AWAITING_APPROVAL -> IN_PROGRESS allowed (approved, executing); leaving AWAITING_APPROVAL for IN_PROGRESS/DONE needs a HUMAN | Transport is "booked, awaiting pickup" after approval, so a cancellation can reopen it | P2 |
| D21 | Hospital systems (pharmacy, crews, EPR letter signing) are simulated on the clock; agents can't set TTO status or complete transport | Agents never impersonate staff | P2 |
| D22 | Cancelled booking's slot stays taken (vehicle went elsewhere) | Makes the rebook land on 12:30 -> departure 12:40, matching the dossier story | P2 |
| D23 | CLI paths without leading `/`; CLI undoes Git Bash path rewriting and only accepts known API roots | Found live: Git Bash turned `/health` into `C:/Program Files/Git/health` | P3 |
| D24 | `.claude/settings.json` committed: allow `read:*`/`test:*`, ask `write:*` | Same approval behaviour for anyone who clones and runs the agents in this folder | P3 |
| D25 | MFFD is entered by the doctor in the hospital system (sim EPR / scenario runner), never by an agent from chat; agents read it and open the room | `discharge-lead` refused to record a clinical decision under a doctor's name; that refusal is correct | P3 spike |
| D26 | Contract 1.2.0: agents act as `{"type":"agent","role":"coordinator"}`; task PATCH takes `detail` for human attribution ("reported by nurse-amy: ...") | `discharge-lead` refused to pose as a nurse or sign off something it didn't witness | P3 spike |
| D27 | Booking accepts `approver`: request + nurse confirm in one call (rolled back if approver isn't a human nurse) | One approval card per decision instead of two | P4 |
| D28 | Agents: `discharge-lead` (`@lead`, exclusive), `pharmacy-liaison` (`@meds`), `transport-liaison` (`@transport`); Console instructions point to `switch/roles/*.md` | Role behaviour is versioned in the repo; one human (nurse-amy) approves | P4 |
| D29 | CLI encodes `+` in query strings | Timezone offsets in `after=` were turning into spaces | P4 |
| D30 | Board = one static page `homeward/sim/static/board.html` (vanilla JS, polls `/board/ward` every 2 s, text-only rendering of ledger); shows baseline-vs-actual departure | No build step; agent-written text can't inject HTML | P5 |
| D31 | `TARGET_MET_AT`: transport's 30-min target is met when the booking is approved (IN_PROGRESS); TTO clocks keep running while in progress | Arthur showed 'Needs attention' with a confirmed car | P5 |
| D32 | Scenario runner `homeward/scenario.py` (`homeward.py scenario margaret [--auto]`): plays only the hospital (EPR, pharmacy, provider, clock) live; `--auto` also plays agents + nurse | One command shows the whole day; live demo stays human+agent in Slack | P6 |
| D33 | TTO verify 50 min + dispense 55 min | Agents request at 10:00 in practice; keeps ready 11:45 -> pickup 12:15 -> cancel -> 12:30 -> leave 12:40 | P6 |
| D34 | BLOCKED restarts the task's target clock (READY no longer does) | Cancel at 11:20 escalated instantly ('80 min since ready') | P6 |
| D35 | `ward-clerk`: deterministic custom agent registered via `POST /agents` (registration key from the human's Gateway account, `session_passive`), posting with `POST /agents/{id}/message`; announces only hospital-side events and addresses the owning job | LLM agents act only when addressed; nurse had to relay the 11:20 cancellation | ward clerk |
