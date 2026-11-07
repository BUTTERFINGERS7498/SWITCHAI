"""Scenario runner (P6). Stdlib only: talks to the running sim over HTTP.

  python scripts/homeward.py scenario margaret          live demo: drives the clock and hospital events,
                                                         pauses for the humans and agents in Slack
  python scripts/homeward.py scenario margaret --auto [--delay 30]   no Slack: also plays the agents and the nurse,
                                                         so anyone can see the whole day in one command

The runner only ever plays the *hospital* (doctor's EPR entries, pharmacy, transport provider, the clock).
In live mode, everything agents and the nurse do happens in Slack through Switch.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta

BASE = os.environ.get("HOMEWARD_URL", "http://127.0.0.1:" + os.environ.get("HOMEWARD_PORT", "8765")).rstrip("/")
DAY = "2026-11-07T"
BED = 12
DELAY = 0   # --delay N: the pharmacy runs N minutes late (a hospital system event, not an agent action)
DOCTOR = {"id": "dr-raj", "role": "doctor", "type": "human"}
NURSE = {"id": "nurse-amy", "role": "nurse", "type": "human"}
LEAD = {"id": "discharge-lead", "role": "coordinator", "type": "agent"}
MEDS = {"id": "pharmacy-liaison", "role": "coordinator", "type": "agent"}
TRANSPORT = {"id": "transport-liaison", "role": "coordinator", "type": "agent"}


class SimError(RuntimeError):
    pass


def call(method: str, path: str, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(BASE + path, data=data, method=method,
                                 headers={"content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            raw, ctype = r.read().decode(), r.headers.get("content-type", "")
    except urllib.error.HTTPError as ex:
        raise SimError(f"{method} {path} -> {ex.code}: {ex.read().decode()[:300]}") from ex
    except (urllib.error.URLError, OSError) as ex:
        raise SimError(f"sim not reachable at {BASE} ({ex}). Start it: python scripts/homeward.py demo") from ex
    return json.loads(raw) if "json" in ctype else raw


def at(hhmm: str) -> str:
    return f"{DAY}{hhmm}:00+00:00"


def hhmm(iso: str) -> str:
    return iso[11:16] if iso else "--:--"


def clock_to(hhmm_: str, quiet=False):
    out = call("POST", "/clock", {"now": at(hhmm_)})
    if not quiet:
        for e in out["events"]:
            if e["bed"] == BED or e["action"] in ("escalation", "patient.departed"):
                print(f"    {hhmm(e['at'])}  bed {e['bed']}  {e['action']}  {e.get('detail') or ''}")
    return out


def task_id(kind: str) -> str:
    plan = call("GET", f"/patients/{BED}/plan")
    return next(t["id"] for t in plan["tasks"] if t["kind"] == kind)


def active_booking():
    board = call("GET", "/board/ward")
    bed = next(b for b in board["beds"] if b["bed"] == BED)
    live = [b for b in bed.get("bookings", []) if b["status"] in ("confirmed", "pending_approval")]
    return live[-1] if live else None


def banner(text: str):
    print("\n" + "=" * 72 + f"\n{text}\n" + "=" * 72)


def pause(auto: bool, instructions: list[str]):
    if auto:
        return
    print("\n  In Slack:")
    for line in instructions:
        print("    " + line)
    try:
        input("\n  Press Enter when done (Ctrl+C to stop) ")
    except EOFError:
        pass


def blocker_line():
    b = call("GET", f"/patients/{BED}/blocker")
    print(f"  Board: {b['summary']}  ({b['cost']['hours']} bed-hours, £{b['cost']['gbp']})")
    return b


# --- auto-mode actors (what the agents + nurse do in Slack, done over the API) ---------------------
def auto_tto():
    out = call("POST", f"/patients/{BED}/tto/request", {"actor": MEDS})
    print(f"  [@meds] TTO requested; ready {hhmm(out['ready_eta'])}  (approval card: Allow once)")


def auto_book():
    el = call("GET", f"/patients/{BED}/transport/eligibility")
    slots = call("GET", f"/transport/slots?vehicle={el['vehicle']}&after={el['earliest_pickup'].replace('+', '%2B')}")
    slot = slots["slots"][0]
    b = call("POST", f"/patients/{BED}/transport/bookings", {"slot": slot, "actor": TRANSPORT, "approver": NURSE})
    print(f"  [@transport] {el['vehicle']} pickup {hhmm(b['slot'])} (earliest {hhmm(el['earliest_pickup'])}), "
          f"approved by {b['approved_by']}")


def auto_family_and_belongings():
    for kind, what in (("family_informed", "daughter Sarah told 10:05"), ("belongings", "belongings packed 10:10")):
        call("PATCH", f"/patients/{BED}/tasks/{task_id(kind)}",
             {"status": "done", "actor": LEAD, "detail": f"reported by nurse-amy: {what}"})
    print("  [@lead] family informed + belongings packed (reported by nurse-amy)")


# --- the day -------------------------------------------------------------------------------------
def margaret(auto: bool) -> int:
    banner("Homeward · Margaret Jones, 82, bed 12 · synthetic training ward")
    print("  Without Homeward she was told at 10:00 she could go home, and left at 19:10.")
    call("POST", "/reset", {"scenario": "margaret"})

    banner("10:00  Doctor declares Margaret medically fit in the EPR (pathway 0)")
    call("POST", f"/patients/{BED}/mffd", {"pathway": "P0", "actor": DOCTOR})
    blocker_line()
    pause(auto, ["#ward-7:  @lead Bed 12 Margaret Jones has been declared medically fit in the EPR, pathway 0.",
                 "          Please open her discharge in #discharge-bed-12.",
                 "Then let the agents work: @meds sends the TTO request (approve the card),",
                 "@transport proposes a pickup (say 'go ahead', approve the card).",
                 "#discharge-bed-12:  @lead I told Margaret's daughter Sarah at 10:05 that she's going home",
                 "          today, and her belongings are packed.   (approve the card(s))"])
    if auto:
        auto_tto()
        if DELAY:
            call("POST", "/events", {"type": "tto_delayed", "bed": BED, "minutes": DELAY})
            print(f"  [pharmacy system] delayed {DELAY} min; medicines now ready {hhmm(call('GET', f'/patients/{BED}/tto')['ready_eta'])}")
        auto_book()
        auto_family_and_belongings()
    blocker_line()

    banner("11:00  Doctor signs the discharge letter in the EPR")
    clock_to("11:00")
    call("POST", "/events", {"type": "letter_signed", "bed": BED, "doctor": "dr-raj"})

    bk = active_booking()
    if bk is None:
        print("\n  No transport booking yet: book it before continuing (live mode), or check the agents.")
        pause(auto, ["#discharge-bed-12:  @transport please book transport home for bed 12  (approve the card)"])
        bk = active_booking()
    if bk is None:
        print("  Still no booking. Stopping.")
        return 1

    banner(f"11:20  Curveball: the transport provider cancels the {hhmm(bk['slot'])} pickup")
    call("POST", "/events", {"type": "transport_cancelled", "bed": BED, "at": at("11:20"), "reason": "vehicle breakdown"})
    clock_to("11:20")
    blocker_line()
    pause(auto, ["#discharge-bed-12:  @transport the board shows the transport was cancelled, please sort it",
                 "          (say 'yes, book it', approve the card)"])
    if auto:
        auto_book()

    bk = active_booking()
    if bk is None or bk["status"] != "confirmed":
        print("  No confirmed rebooking yet. Rebook and approve it, then run the scenario again from here.")
        return 1

    banner("11:30  Shift change: the night nurse asks for a handover")
    clock_to("11:30", quiet=True)
    if auto:
        print("  [@lead] " + call("GET", f"/patients/{BED}/handover").replace("\n", "\n          "))
    pause(auto, ["#discharge-bed-12:  @lead what's left for bed 12?"])

    pickup = datetime.fromisoformat(bk["slot"])
    leave = (pickup + timedelta(minutes=10)).strftime("%H:%M")
    banner(f"{hhmm(bk['slot'])}  Crew collects Margaret · {leave} she leaves the ward")
    clock_to(leave)
    p = call("GET", f"/patients/{BED}")
    if not p.get("departed_at"):
        blocker_line()
        print("  Margaret has not left: something is still open (see the board).")
        return 1

    cost = call("GET", f"/patients/{BED}/blocker")["cost"]
    ledger = call("GET", f"/patients/{BED}/ledger")
    approvals = [x for x in ledger if x["approval_id"] and x["actor"]["type"] == "human"]
    agent_writes = [x for x in ledger if x["actor"]["type"] == "agent"]
    base = datetime.fromisoformat(at("19:10"))
    saved = (base - datetime.fromisoformat(p["departed_at"])).total_seconds() / 3600
    banner("Result")
    print(f"  Margaret went home at {hhmm(p['departed_at'])} instead of 19:10.")
    print(f"  Bed-hours after fit: {cost['hours']} (£{cost['gbp']}) · freed vs baseline: {saved:.1f} h "
          f"(£{saved * 23.42:.0f})")
    print(f"  Human approvals: {len(approvals)} ({', '.join(sorted({a['actor']['id'] for a in approvals}))}) · "
          f"agent actions: {len(agent_writes)} · clinical actions by agents: 0")
    print(f"  Board: {BASE}/board")
    return 0


SCENARIOS = {"margaret": margaret}


def main(args: list[str]) -> int:
    names = [a for a in args if not a.startswith("--")]
    name = names[0] if names else "margaret"
    if name not in SCENARIOS:
        print(f"unknown scenario {name}; known: {', '.join(SCENARIOS)}")
        return 2
    try:
        global DELAY
        DELAY = int(args[args.index("--delay") + 1]) if "--delay" in args else 0
        return SCENARIOS[name]("--auto" in args)
    except SimError as ex:
        print(f"\n  ERROR: {ex}")
        return 3
    except KeyboardInterrupt:
        print("\n  stopped.")
        return 130


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
