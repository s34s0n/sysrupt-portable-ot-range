"""CTF Management CLI -- REPL for managing the auto-detection engine."""

import json
import os
import sys
import time

import redis

from ctf.engine import CHALLENGES, TOTAL_POINTS

# ANSI color codes
GREEN = "\033[32m"
AMBER = "\033[33m"
GRAY = "\033[90m"
RED = "\033[31m"
BOLD = "\033[1m"
RESET = "\033[0m"
CYAN = "\033[36m"
CLEAR = "\033[2J\033[H"


def _connect():
    """Connect to Redis."""
    r = redis.Redis(host="127.0.0.1", port=6379, decode_responses=True)
    r.ping()
    return r


def _get_state(r):
    """Read CTF state from Redis."""
    score = int(r.get("ctf:score") or 0)
    raw = r.get("ctf:flags_captured")
    captured = json.loads(raw) if raw else []
    start_time = r.get("ctf:start_time")
    hint_raw = r.get("ctf:hint_state")
    hint = json.loads(hint_raw) if hint_raw else {"hint_level": 0, "elapsed_min": 0}
    return score, captured, start_time, hint


def _fmt_elapsed(start_time):
    """Format elapsed time."""
    if not start_time:
        return "--:--"
    elapsed = time.time() - float(start_time)
    m, s = divmod(int(elapsed), 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def _render_table(r, clear_screen=False):
    """Render the challenge status table."""
    score, captured, start_time, hint = _get_state(r)
    lines = []

    if clear_screen:
        lines.append(CLEAR)

    lines.append(f"\n{BOLD}{CYAN}=== SYSRUPT OT RANGE CTF ==={RESET}")
    lines.append(f"Score: {BOLD}{score}{RESET}/{TOTAL_POINTS}  |  "
                 f"Elapsed: {_fmt_elapsed(start_time)}  |  "
                 f"Hints: L{hint.get('hint_level', 0)}/{hint.get('max_level', 3)}")
    lines.append(f"{GRAY}{'─' * 60}{RESET}")
    lines.append(f"{'ID':>4}  {'PTS':>5}  {'STATUS':>8}  {'NAME'}")
    lines.append(f"{GRAY}{'─' * 60}{RESET}")

    for ch in CHALLENGES:
        cid = str(ch.id)
        if cid in captured:
            color = GREEN
            status = "SOLVED"
        else:
            color = GRAY
            status = "LOCKED"

        lines.append(
            f"{color}  {ch.id:02d}  {ch.points:>5}  {status:>8}  {ch.name}{RESET}"
        )

    lines.append(f"{GRAY}{'─' * 60}{RESET}")
    lines.append(f"Captured: {len(captured)}/{len(CHALLENGES)}")
    lines.append("")
    return "\n".join(lines)


def cmd_status(r):
    """Pretty-print challenge table."""
    print(_render_table(r))


def cmd_reset(r):
    """Clear all CTF state."""
    keys = r.keys("ctf:*")
    if keys:
        r.delete(*keys)
    r.delete("physics:victory")
    print(f"{AMBER}CTF state cleared.{RESET}")


def cmd_award(r, n):
    """Manually award a challenge (publishes event so running engine picks it up)."""
    try:
        cid = int(n)
    except ValueError:
        print(f"{RED}Invalid challenge number.{RESET}")
        return

    ch = None
    for c in CHALLENGES:
        if c.id == cid:
            ch = c
            break
    if not ch:
        print(f"{RED}Challenge {cid} not found.{RESET}")
        return

    # Check already captured
    raw = r.get("ctf:flags_captured")
    captured = json.loads(raw) if raw else []
    if str(cid) in captured:
        print(f"{AMBER}CH-{cid:02d} already captured.{RESET}")
        return

    # Award directly via Redis (engine pattern)
    captured.append(str(cid))
    score = int(r.get("ctf:score") or 0) + ch.points

    if not r.exists("ctf:start_time"):
        r.set("ctf:start_time", str(time.time()))

    pipe = r.pipeline()
    pipe.set("ctf:score", str(score))
    pipe.set("ctf:flags_captured", json.dumps(captured))
    pipe.set("ctf:last_flag_time", str(time.time()))
    pipe.set("ctf:active", "1")
    pipe.set("ctf:total_challenges", str(len(CHALLENGES)))
    pipe.set("ctf:total_points", str(TOTAL_POINTS))
    detail = {
        "id": cid,
        "name": ch.name,
        "points": ch.points,
        "captured_at": time.time(),
    }
    pipe.set(f"ctf:challenge:{cid}", json.dumps(detail))
    pipe.execute()

    # Publish for display
    r.publish("ctf:flag_captured", json.dumps(detail))

    print(f"{GREEN}Awarded CH-{cid:02d}: {ch.name} (+{ch.points} pts, total {score}){RESET}")


def cmd_simulate(r):
    """Auto-award all 10 challenges with 3-second delays."""
    print(f"\n{BOLD}{CYAN}=== SIMULATION MODE ==={RESET}")
    print("Awarding all 10 challenges with 3-second delays...\n")

    # Reset first
    cmd_reset(r)
    time.sleep(0.5)

    # Set start time
    r.set("ctf:start_time", str(time.time()))
    r.set("ctf:active", "1")
    r.set("ctf:total_challenges", str(len(CHALLENGES)))
    r.set("ctf:total_points", str(TOTAL_POINTS))

    for ch in CHALLENGES:
        cmd_award(r, str(ch.id))
        time.sleep(3)

    print(f"\n{GREEN}{BOLD}SIMULATION COMPLETE!{RESET}")
    print(f"Final score: {r.get('ctf:score')}/{TOTAL_POINTS}")
    cmd_status(r)


def cmd_monitor(r):
    """Live updating status table every 1 second."""
    print("Monitoring... Press Ctrl+C to stop.\n")
    try:
        while True:
            print(_render_table(r, clear_screen=True), end="", flush=True)
            time.sleep(1)
    except KeyboardInterrupt:
        print(f"\n{AMBER}Monitor stopped.{RESET}")


def main():
    try:
        r = _connect()
    except Exception as exc:
        print(f"{RED}Cannot connect to Redis: {exc}{RESET}")
        sys.exit(1)

    print(f"{BOLD}{CYAN}Sysrupt OT Range CTF CLI{RESET}")
    print("Commands: status, reset, award N, simulate, monitor, quit\n")

    while True:
        try:
            line = input(f"{CYAN}ctf>{RESET} ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not line:
            continue

        parts = line.split()
        cmd = parts[0].lower()

        if cmd == "quit" or cmd == "exit":
            break
        elif cmd == "status":
            cmd_status(r)
        elif cmd == "reset":
            cmd_reset(r)
        elif cmd == "award":
            if len(parts) < 2:
                print(f"{RED}Usage: award N{RESET}")
            else:
                cmd_award(r, parts[1])
        elif cmd == "simulate":
            cmd_simulate(r)
        elif cmd == "monitor":
            cmd_monitor(r)
        else:
            print(f"{AMBER}Unknown command: {cmd}{RESET}")
            print("Commands: status, reset, award N, simulate, monitor, quit")


if __name__ == "__main__":
    main()
