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
