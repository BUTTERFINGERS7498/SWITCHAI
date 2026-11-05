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
