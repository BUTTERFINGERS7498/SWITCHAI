"""ward-clerk: a deterministic Switch agent (no LLM) that tells the rooms what the hospital systems did.

The LLM agents only act when someone addresses them. The clerk closes that gap: it watches the Homeward
sim's ledger and posts plain-language announcements into the Switch rooms, addressing the job that owns
the next step (`@lead`, `@meds`, `@transport`). It never changes hospital state; it only reads the sim
and posts messages.

  python scripts/homeward.py clerk register        one-off; needs SWITCH_REGISTRATION_KEY in the environment
  python scripts/homeward.py clerk rooms           list the Switch rooms the clerk belongs to
  python scripts/homeward.py clerk run [--bed 12] [--ward-room ward-7] [--bed-room discharge-bed-12]
                                       [--interval 2] [--dry-run] [--from-start]

Switch agent protocol used: POST /agents (register, with a registration key), POST /agents/{id}/ops/list_rooms,
POST /agents/{id}/message {room_id, content}. Credentials live in .homeward/clerk.json (git-ignored) and are
never printed. Stdlib only.
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable, Optional

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / ".homeward" / "clerk.json"
SIM = os.environ.get("HOMEWARD_URL", "http://127.0.0.1:" + os.environ.get("HOMEWARD_PORT", "8765")).rstrip("/")
SWITCH = os.environ.get("SWITCH_URL", "http://127.0.0.1:52755").rstrip("/")
NAME = "ward-clerk"

# Which job owns the next step for each task kind.
JOB_FOR_KIND = {"tto_verify": "meds", "tto_dispense": "meds", "transport_booked": "transport"}
PEOPLE = {"dr-raj": "Dr Raj", "dr-on-call": "the on-call doctor", "nurse-amy": "Nurse Amy"}


class HttpError(RuntimeError):
    def __init__(self, status: int, body: str):
        super().__init__(f"HTTP {status}: {body[:200]}")
        self.status, self.body = status, body


def http(method: str, url: str, body=None, token: Optional[str] = None):
    headers = {"content-type": "application/json", "accept": "application/json"}
    if token:
        headers["authorization"] = "Bearer " + token
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            raw = r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as ex:
        raise HttpError(ex.code, ex.read().decode("utf-8", "replace")) from ex
    return json.loads(raw) if raw else {}


# --- the words (pure, unit-tested) ---------------------------------------------------------------
def hhmm(iso: Optional[str]) -> str:
    return iso[11:16] if iso else "?"


def announce(entry: dict, plan: dict) -> Optional[tuple[str, str]]:
    """Map one sim ledger entry to (room, message) or None. room is "ward" or "bed".
    Only hospital-side events are announced; agents and nurses already speak for themselves."""
    first = plan["name"].split()[0]
    bed = plan["bed"]
    tasks = {t["id"]: t for t in plan.get("tasks", [])}
    task = tasks.get(entry.get("task_id") or "")
    kind, label = (task["kind"], task["label"]) if task else (None, None)
    actor = entry["actor"]
    action, detail = entry["action"], entry.get("detail") or ""
    who = PEOPLE.get(actor["id"], actor["id"])

    if action == "patient.mffd":
        return ("ward", f"@lead EPR update: {who} has declared {plan['name']} (bed {bed}) medically fit for "
                        f"discharge, {detail}. Please open {first}'s discharge in #discharge-bed-{bed}.")
    if action == "patient.departed":
        return ("ward", f"{plan['name']} left the ward at {hhmm(entry['at'])}. Bed {bed} is free.")
    if action == "task.blocked" and kind == "transport_booked" and actor["type"] != "agent":
        if "crew" in detail:
            return ("bed", f"@transport The crew arrived for bed {bed} at {hhmm(entry['at'])} but {first} wasn't "
                           f"ready, so they left. Please rebook for when everything is done, and tell @lead what's open.")
        return ("bed", f"@transport Heads up: the transport provider cancelled {first}'s pickup "
                       f"({detail.split('(')[-1].rstrip(')') or 'no reason given'}). The board shows bed {bed} "
                       f"blocked. Please find the next safe slot and ask a nurse to approve it.")
    if action == "task.done" and actor["type"] == "system" and kind == "tto_dispense":
        return ("bed", f"Pharmacy: {first}'s discharge medicines are ready for collection on the ward "
                       f"({hhmm(entry['at'])}).")
    if action == "task.done" and kind == "letter_signed" and actor["type"] == "human":
        return ("bed", f"EPR: {who} signed {first}'s discharge letter at {hhmm(entry['at'])}.")
    if action == "tto.delayed":
        return ("bed", f"@meds @transport Pharmacy update for bed {bed}: {detail}. Check the pickup still works.")
    if action == "escalation":
        return ("bed", f"@lead Escalation for bed {bed}: {detail}.")
    if action == "nudge" and label:
        job = JOB_FOR_KIND.get(kind, "lead")
        m = re.search(r"\((\d+) min\)", detail)
        target = f"{m.group(1)}-minute target" if m else "target time"
        return ("bed", f"@{job} Reminder for bed {bed}: {label} for {first} is past its {target}.")
    return None


# --- Switch side ----------------------------------------------------------------------------------
def load_config() -> dict:
    if not CONFIG.exists():
        raise SystemExit(f"No clerk registration at {CONFIG}. Run: python scripts/homeward.py clerk register")
    return json.loads(CONFIG.read_text(encoding="utf-8"))


def cmd_register(args: list[str]) -> int:
    key = os.environ.get("SWITCH_REGISTRATION_KEY")
    if not key:
        print("Set SWITCH_REGISTRATION_KEY first (Switch Gateway -> API Keys -> Create Registration Key).\n"
              "PowerShell:  $env:SWITCH_REGISTRATION_KEY = '<key>'; python scripts/homeward.py clerk register")
        return 2
    body = {
        "name": NAME,
        "display_name": "Ward clerk",
        "description": "Deterministic Homeward clerk: announces hospital-system events (EPR, pharmacy, transport) "
                       "to the ward rooms. Never changes hospital state.",
        "connector_type": "homeward-clerk",
        "integration_profile": {"connection_model": "session_passive", "message_exchange": True,
                                "pre_invocation_mediation": [], "post_invocation_mediation": [],
                                "event_reporting": []},
        "overwrite": "--overwrite" in args,
    }
    try:
        out = http("POST", f"{SWITCH}/agents", body, token=key)
    except HttpError as ex:
        hint = {401: "the registration key was rejected", 409: "ward-clerk already exists: add --overwrite to re-issue its key"}
        print(f"Registration failed ({hint.get(ex.status, ex)}).")
        return 1
    CONFIG.parent.mkdir(exist_ok=True)
    CONFIG.write_text(json.dumps({"switch_url": SWITCH, "agent_id": out["id"], "api_key": out["api_key"]}, indent=2),
                      encoding="utf-8")
    print(f"Registered {NAME} (agent id {out['id']}). Credentials saved to {CONFIG} (git-ignored).\n"
          f"Next: in Slack, run  !invite-agent @{NAME}  in #ward-7 and #discharge-bed-12.")
    return 0


def list_rooms(cfg: dict) -> list[dict]:
    return http("POST", f"{cfg['switch_url']}/agents/{cfg['agent_id']}/ops/list_rooms", {}, token=cfg["api_key"])


def resolve_room(rooms: list[dict], name: str) -> Optional[str]:
    """Match a Switch room by its name, e.g. 'SwitchAi: discharge-bed-12' for 'discharge-bed-12'."""
    want = name.lstrip("#").lower()
    for r in rooms:
        n = (r.get("name") or "").lower()
        if n == want or n.endswith(": " + want) or n.endswith(want):
            return r["room_id"]
    return None


def cmd_rooms(_args: list[str]) -> int:
    cfg = load_config()
    rooms = list_rooms(cfg)
    if not rooms:
        print(f"{NAME} is in no rooms yet. In Slack: !invite-agent @{NAME}")
    for r in rooms:
        print(f"{r['room_id']}  {r['name']}")
    return 0


# --- the loop -------------------------------------------------------------------------------------
def opt(args: list[str], name: str, default):
    return type(default)(args[args.index(name) + 1]) if name in args else default


def run(args: list[str], post: Optional[Callable[[str, str], None]] = None, max_cycles: Optional[int] = None,
        sleep=time.sleep) -> int:
    bed = opt(args, "--bed", 12)
    interval = opt(args, "--interval", 2.0)
    dry = "--dry-run" in args
    rooms = {"ward": opt(args, "--ward-room", "ward-7"), "bed": opt(args, "--bed-room", f"discharge-bed-{bed}")}
    if post is None:
        if dry:
            post = lambda room, text: print(f"[dry-run -> {room}] {text}")  # noqa: E731
        else:
            cfg = load_config()
            ids = {}
            available = list_rooms(cfg)
            for key, name in rooms.items():
                ids[key] = resolve_room(available, name)
                if not ids[key]:
                    print(f"{NAME} isn't in a room called {name}. In Slack, in that channel: !invite-agent @{NAME}")
                    return 1

            def post(room, text, _ids=ids, _cfg=cfg):
                http("POST", f"{_cfg['switch_url']}/agents/{_cfg['agent_id']}/message",
                     {"room_id": _ids[room], "content": text}, token=_cfg["api_key"])

    seen = None if "--from-start" not in args else 0
    print(f"{NAME} watching bed {bed} on {SIM}; posting to #{rooms['ward']} and #{rooms['bed']}"
          f"{' (dry run)' if dry else ''}. Ctrl+C to stop.")
    cycles = 0
    while max_cycles is None or cycles < max_cycles:
        cycles += 1
        try:
            ledger = http("GET", f"{SIM}/patients/{bed}/ledger")
            if seen is None:              # first look: announce only what happens from now on
                seen = len(ledger)
            elif len(ledger) < seen:      # the sim was reset: start again from the top
                seen = 0
            fresh = ledger[seen:]
            if fresh:
                try:
                    plan = http("GET", f"{SIM}/patients/{bed}/plan")
                except HttpError:
                    plan = {"bed": bed, "name": http("GET", f"{SIM}/patients/{bed}")["name"], "tasks": []}
                for entry in fresh:
                    msg = announce(entry, plan)
                    if msg:
                        post(*msg)
                        print(f"  {hhmm(entry['at'])} -> #{rooms[msg[0]]}: {msg[1]}")
                seen = len(ledger)
        except HttpError as ex:
            if ex.status in (401, 403):
                print(f"Switch refused the clerk ({ex.status}). Is it invited to both rooms, and is its key current?")
                return 1
            print(f"  waiting: {ex}")
        except (urllib.error.URLError, OSError) as ex:
            print(f"  waiting for the sim or Switch ({ex})")
        if max_cycles is None or cycles < max_cycles:
            sleep(interval)
    return 0


def main(args: list[str]) -> int:
    cmd = args[0] if args else ""
    if cmd == "register":
        return cmd_register(args[1:])
    if cmd == "rooms":
        return cmd_rooms(args[1:])
    if cmd == "run":
        try:
            return run(args[1:])
        except KeyboardInterrupt:
            print("\nclerk stopped.")
            return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
