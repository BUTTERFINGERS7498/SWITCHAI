# Switch setup for Homeward (P4)

Built during the hackathon on Switch Console 0.40.1 / Switch 0.31.0, local server, Slack connected (see `docs/SPIKE.md`).
One human (the discharge nurse, "nurse-amy") approves; doctors, pharmacy and crews are simulated hospital systems.

## 0. Before you start
- Switch Console running with a local server and the Slack connection (Slack app from `switch/slack-app-manifest.json`).
- In `repo/`: `python scripts/homeward.py setup`, then leave `python scripts/homeward.py demo` running (port 8765).
- `repo/.claude/settings.json` is in the repo: agents may run `homeward.py read` freely; every `homeward.py write`
  raises an approval card.

## 1. Channels → rooms (Slack)
Create two channels and turn each into a Switch room:
```
#ward-7              /invite @Agent Switch      (ward hub: doctors announce MFFD, night nurse asks for status)
#discharge-bed-12    /invite @Agent Switch      (one room per patient)
```

## 2. Agents (Switch Console → Your Agents → + card)
Same settings for all three: **Run location** This computer · **Directory** the `repo` folder · **Agent provider**
Claude Code · **Auto mode** on · **Bypass permissions** off · **Who can talk to your agent** Me and my agents (default).

| Name | Description | Agent instructions |
|---|---|---|
| `discharge-lead` (exists) | Coordinates non-clinical discharge logistics for one patient; never makes clinical decisions. | `You are discharge-lead. At the start of every session read switch/room-instructions.md and switch/roles/discharge-lead.md in your working directory and follow them exactly.` |
| `pharmacy-liaison` | Sends and tracks discharge-medicine (TTO) requests; never changes medicines. | `You are pharmacy-liaison. At the start of every session read switch/room-instructions.md and switch/roles/pharmacy-liaison.md in your working directory and follow them exactly.` |
| `transport-liaison` | Books patient transport timed to when medicines and letter are ready. | `You are transport-liaison. At the start of every session read switch/room-instructions.md and switch/roles/transport-liaison.md in your working directory and follow them exactly.` |

For `discharge-lead`, update its instructions under its agent settings (or leave them; the role file wins once read).

## 3. Put agents in rooms (type in the channel)
```
#discharge-bed-12   !invite-agent @discharge-lead
                    !invite-agent @pharmacy-liaison
                    !invite-agent @transport-liaison
#ward-7             !invite-agent @discharge-lead
```

## 4. Room instructions
Switch Console → open `discharge-bed-12` → **Configuration** → **Instructions** → paste the block from
`switch/room-instructions.md` → **Save**. Do the same for `ward-7`.

## 5. Jobs (roles) and links (type in `#discharge-bed-12`, one message at a time)
A job is defined once (name + instructions written *to the agent that takes it*), then taken. An agent receives the
job's instructions when it takes the job, so define all three first. Each agent holds one job at a time.

Define the jobs:
```
@discharge-lead define an exclusive role called lead, with these instructions: you own this patient's non-clinical discharge plan, the checklist room document and the answer to "what's left?". Follow switch/roles/discharge-lead.md and switch/room-instructions.md.
@discharge-lead define a shared role called meds, with these instructions: send and track the discharge-medicine (TTO) request; never change medicines or set TTO status. Follow switch/roles/pharmacy-liaison.md and switch/room-instructions.md.
@discharge-lead define a shared role called transport, with these instructions: book transport for when medicines and letter are ready, with a nurse's approval card, and rebook on cancellation. Follow switch/roles/transport-liaison.md and switch/room-instructions.md.
```
Fill them:
```
@discharge-lead take the lead role
@pharmacy-liaison take the meds role
@transport-liaison take the transport role
```
Link the rooms (links are one-way, so both directions):
```
@discharge-lead link this room to #ward-7 with the label "ward hub", and link #ward-7 back to this room with the label "bed 12"
```
Check: `!roles` shows lead → discharge-lead, meds → pharmacy-liaison, transport → transport-liaison.
Alternative: Gateway → room page → **Add role** / **Add linked room**.

## 6. Conversation settings (type in `#discharge-bed-12`)
```
!follow-ups on
```

## 7. Check
```
/agents-status        three agents present
/roles                lead → discharge-lead, meds → pharmacy-liaison, transport → transport-liaison
/list-documents       (discharge-plan-bed-12 appears after the first run)
```

## Which Switch features this uses (for the README "unplug" table)
Rooms per patient · room instructions · exclusive and shared jobs addressed as `@lead` / `@meds` / `@transport` ·
linked rooms (ward hub ↔ bed room) · room documents (checklist) · approval cards on every write (Allow once / Decline,
approver recorded) · who-can-instruct policy · follow-ups in threads · agent-to-agent hand-offs.
