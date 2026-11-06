# Switch spike (P0) — ALL 5 CHECKS PASS

Machine: Sarvagya's Windows 11 laptop. Switch Console v0.40.1 (installer signed by SandboxAQ, SHA-256
575262E7…2332). Docker Desktop 29.8.0. Claude Code 2.1.319. Chat surface: Slack (Team RE:SET), Socket Mode,
so no public URL is needed (per docs.switchagents.ai Slack page).

| # | Check | Result | Notes / fallback used |
|---|---|---|---|
| 1 | Local server running from Console | PASS (2nd attempt) | First start failed: "switch-core stopped during startup", empty switch-core.log. Native mode (bundled Postgres 16 + switch-core 0.31.0 venv), not Docker. Run by hand, switch-core started fine, so the likely cause is a slow first start (fresh venv). Console retry at 01:47 IST succeeded; server on 127.0.0.1:52755 returns 200. If it recurs: quit Console fully and reopen. |
| 2 | Claude Code agent answers in a Slack room (by name, then by @role) | PASS (by name) | `discharge-lead` (Claude Code, this computer, dir = repo, Auto mode on, bypass off, "Me and my agents") registered 02:09, added to `homeward-spike`, replied in Slack. Role addressing not tested yet (P4). |
| 3 | Room document write then read-back | PASS | 02:13: agent created room doc `spike-checklist`, read back "bed 12: TTO pending" (3 tool calls, 10 s). |
| 4 | Approval card on a write command while reads are auto-allowed | PASS | 03:35: with `.claude/settings.json` (allow `read:*`, ask `write:*`) and a fresh session, `homeward.py write PATCH patients/12/tasks/t5` showed a Slack card with buttons before running; Sarvagya clicked Allow. Reads run without a card. |
| 5 | Agent session can run our CLI | PASS | 02:12: agent ran `python scripts/homeward.py test` in the repo, replied "9 passed in 0.02s" (2 tool calls, 11 s). `/clock` arrives with the sim (P2). |

## Slack connection (02:03 IST)
Connected as "SwitchAi": adapter authenticated as `agent_switch` in Team RE:SET, Socket Mode session established,
Sarvagya's Slack user linked as a human actor. Expected warnings: no user groups on a free plan (so no `@` autocomplete),
localhost-only Console links. Bridge hears nothing until `/invite @Agent Switch` is run in a channel.
02:04: `/invite @Agent Switch` in `#homeward-spike` (C0CFNESS0RG) auto-created room `sw_room_0a85dc16…`;
`/agents-status` answered "no agents in the room". Slack <-> Switch bridge verified.

## Agent boundary observed (03:20 IST)
Asked to run `homeward.py write POST /patients/12/mffd` with actor `dr-raj`, `discharge-lead` refused: it would record a
medically-fit decision under a doctor's name it couldn't verify. Good behaviour, and demo material. Also seen: Slack
turns typed quotes into curly quotes, so humans must never type JSON; agents build it. The agent's session predated
`write`, so `/reset @discharge-lead` is needed after tool changes.

## First agent write (03:35 IST)
After D26, `discharge-lead` ran `homeward.py write PATCH patients/12/tasks/t5` as itself (agent, coordinator) with
detail "reported by nurse-amy: daughter Sarah told at 10:05". Ledger verified: exactly one change, other tasks untouched.

## Incidents
- 01:47 IST: the bundled Postgres (127.0.0.1:52757, data in `%APPDATA%\switchdash\local-switch-server\native\pgdata`)
  was stopped by our own diagnostic (`pg_ctl stop` on the shared data folder). switch-core kept listening on :52755 but
  returned 500s ("ConnectionRefusedError", "Switch gateway returned 500"). Fixed 01:59 by
  `pg_ctl -D <pgdata> -l <logs>\postgres.log start` (port/address come from `pgdata\switch-console.conf`); switch-core
  reconnected by itself. **Never run pg_ctl against that folder again.** If the Console shows gateway 500s, check
  `netstat -ano | findstr 52757`; the clean fix is quitting Switch Console fully (tray too) and reopening it.

## Findings
- Slack connection needs a Switch Slack app created from the Switch manifest (Agent type), an `xapp-` token
  (`connections:write`) and an `xoxb-` bot token, pasted into Console > server Home > Messaging apps > Connect > Slack.
  Workspace ID: T0CFB5Q9J1G. Tokens are entered by the human only and are never committed.
- `/invite @Agent Switch` in a channel turns it into a Switch room.
- 2026-11-07: Slack app "Agent Switch" created in Team RE:SET from `switch/slack-app-manifest.json`
  (app ID A0CGGV77TS4; 21 bot scopes, 5 bot events, Socket Mode on). Tokens generated and entered by Sarvagya only.
