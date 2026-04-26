#!/usr/bin/env python3
"""Interactive hardware CLI for testing and demos.

Usage:
    python3 -m hardware.cli

Commands:
    status              -- show full hardware state snapshot
    temp [sensor_id]    -- read temperature (all sensors if no id)
    relay <id> on|off   -- set relay state
    led <id> on|off|blink -- set LED state
    reset               -- reset all to initial state
    monitor             -- live view (Ctrl+C to exit)
    help                -- show commands
    quit                -- exit
"""
from __future__ import annotations

import sys
import time

from hardware.manager import HardwareManager

RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
BLUE = "\033[34m"
MAGENTA = "\033[35m"
CYAN = "\033[36m"
GRAY = "\033[90m"

COLOR_MAP = {
    "red": RED,
    "green": GREEN,
    "yellow": YELLOW,
    "blue": BLUE,
    "magenta": MAGENTA,
    "cyan": CYAN,
    "white": RESET,
}


def temp_color(value: float) -> str:
    if value < 30:
        return GREEN
    if value < 40:
        return YELLOW
    return RED


def format_status(hw: HardwareManager) -> str:
    state = hw.get_full_state()
    lines = []
    lines.append(f"{BOLD}=== Sysrupt OT Range Hardware ==={RESET}")
    lines.append(f"Mode: {state['mode']}   Uptime: {state['uptime_seconds']}s   {DIM}{state['timestamp']}{RESET}")
    lines.append("")
    lines.append(f"{BOLD}Temperatures:{RESET}")
    for sid, value in state["temperatures"].items():
        c = temp_color(value)
        lines.append(f"  {sid:<16} {c}{value:6.2f} C{RESET}")
    lines.append("")
    lines.append(f"{BOLD}Relays:{RESET}")
    for rid, rstate in state["relays"].items():
        if rstate:
            marker = f"{GREEN}[ON]{RESET}"
        else:
            marker = f"{GRAY}[off]{RESET}"
        lines.append(f"  {rid:<16} {marker}")
    lines.append("")
    lines.append(f"{BOLD}LEDs:{RESET}")
    for lid, lstate in state["leds"].items():
        led_obj = hw.leds[lid]
        color_code = COLOR_MAP.get(led_obj.get_color(), RESET)
        if lstate == "off":
            marker = f"{GRAY}o{RESET}"
        elif lstate == "blink":
            marker = f"{color_code}*{RESET}"
        else:
            marker = f"{color_code}#{RESET}"
        lines.append(f"  {lid:<16} {marker} ({lstate})")
    return "\n".join(lines)


def cmd_help() -> str:
    return (
        "Commands:\n"
        "  status                    show full hardware state snapshot\n"
        "  temp [sensor_id]          read temperature\n"
        "  relay <id> on|off         set relay state\n"
        "  led <id> on|off|blink     set LED state\n"
        "  reset                     reset all to initial state\n"
        "  monitor                   live view (Ctrl+C to exit)\n"
        "  help                      show commands\n"
        "  quit                      exit"
    )


def run_monitor(hw: HardwareManager) -> None:
    try:
        while True:
            sys.stdout.write("\033[2J\033[H")
            sys.stdout.write(format_status(hw))
            sys.stdout.write("\n\n(Ctrl+C to exit monitor)\n")
            sys.stdout.flush()
            time.sleep(1)
    except KeyboardInterrupt:
        print()
        return


def dispatch(hw: HardwareManager, line: str) -> bool:
    """Returns False to quit."""
    parts = line.strip().split()
    if not parts:
        return True
    cmd = parts[0].lower()
    try:
        if cmd in ("quit", "exit"):
            return False
        elif cmd == "help":
            print(cmd_help())
        elif cmd == "status":
            print(format_status(hw))
        elif cmd == "temp":
            if len(parts) == 1:
                for sid, value in hw.get_all_temperatures().items():
                    print(f"  {sid:<16} {value:6.2f} C")
            else:
                sid = parts[1]
                print(f"  {sid}: {hw.get_temperature(sid):.2f} C")
        elif cmd == "relay":
            if len(parts) != 3:
                print("Usage: relay <id> on|off")
            else:
                rid, val = parts[1], parts[2].lower()
                if val not in ("on", "off"):
                    print("state must be on or off")
                else:
                    hw.set_relay(rid, val == "on")
                    print(f"  relay {rid} -> {val}")
        elif cmd == "led":
            if len(parts) != 3:
                print("Usage: led <id> on|off|blink")
            else:
                lid, val = parts[1], parts[2].lower()
                hw.set_led(lid, val)
                print(f"  led {lid} -> {val}")
        elif cmd == "reset":
            hw.reset()
            print("  reset to initial state")
        elif cmd == "monitor":
            run_monitor(hw)
        else:
            print(f"Unknown command: {cmd}. Type 'help'.")
    except Exception as e:
        print(f"Error: {e}")
    return True


def main() -> int:
    hw = HardwareManager()
    hw.start()
    print("Sysrupt OT Range Hardware CLI. Type 'help' for commands.")
    try:
        while True:
            try:
                line = input("hw> ")
            except EOFError:
                print()
                break
            except KeyboardInterrupt:
                print()
                break
            if not dispatch(hw, line):
                break
    finally:
        hw.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
