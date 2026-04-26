"""IDS Live Alert Monitor -- SOC analyst scrolling alert feed.

ANSI-colored terminal display of IDS alerts in real-time.
Polls Redis ids:alerts every 0.5 seconds.
"""

import json
import os
import sys
import time

import redis

# ANSI color codes
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
BLUE = "\033[34m"
MAGENTA = "\033[35m"
CYAN = "\033[36m"
WHITE = "\033[37m"
BG_RED = "\033[41m"
BG_GREEN = "\033[42m"
BG_YELLOW = "\033[43m"
BG_BLUE = "\033[44m"

SEVERITY_COLORS = {
    "LOW": BLUE,
    "MEDIUM": YELLOW,
    "HIGH": RED,
    "CRITICAL": BOLD + RED,
}

THREAT_COLORS = {
    "NONE": GREEN,
    "LOW": BLUE,
    "MEDIUM": YELLOW,
    "HIGH": RED,
    "CRITICAL": BOLD + BG_RED + WHITE,
}


def clear_screen():
    os.system("clear" if os.name != "nt" else "cls")


def connect_redis():
    for host in ["127.0.0.1", "10.0.3.1", "10.0.4.1"]:
        try:
            r = redis.Redis(host=host, port=6379, decode_responses=True, socket_timeout=1)
            r.ping()
            return r
        except Exception:
            continue
    return None


def format_alert_line(alert: dict) -> str:
    sev = alert.get("severity", "LOW")
    color = SEVERITY_COLORS.get(sev, WHITE)
    ts = alert.get("timestamp", "")
    # Just show HH:MM:SS
    if "T" in ts:
        ts = ts.split("T")[1][:8]
    rule_id = alert.get("rule_id", "")
    name = alert.get("name", "")
    src = alert.get("source_ip", "")
    src_str = f" src={src}" if src else ""

    return f"  {DIM}{ts}{RESET} {color}[{sev:8s}]{RESET} {rule_id} {BOLD}{name}{RESET}{DIM}{src_str}{RESET}"


def draw_header(threat_level: str, alert_count: int, rule_count: int):
    tc = THREAT_COLORS.get(threat_level, WHITE)
    print(f"\n  {BOLD}{CYAN}SYSRUPT IDS MONITOR{RESET}")
    print(f"  {DIM}{'=' * 50}{RESET}")
    print(f"  Threat Level: {tc} {threat_level} {RESET}    "
          f"Alerts: {BOLD}{alert_count}{RESET}    "
          f"Rules: {rule_count}")
    print(f"  {DIM}{'-' * 50}{RESET}")


def main():
    r = connect_redis()
    if not r:
        print("Cannot connect to Redis. Exiting.")
        sys.exit(1)

    seen_count = 0
    print(f"{BOLD}{CYAN}Connecting to IDS...{RESET}")

    try:
        while True:
            clear_screen()

            threat = r.get("ids:threat_level") or "NONE"
            count_raw = r.get("ids:alert_count")
            alert_count = int(count_raw) if count_raw else 0
            active = r.get("ids:active") or "false"

            # Rule count from engine
            rule_count = 24  # static, matches engine

            draw_header(threat, alert_count, rule_count)

            if active != "true":
                print(f"\n  {DIM}IDS engine not active. Waiting...{RESET}")
            else:
                alerts_raw = r.get("ids:alerts")
                if alerts_raw:
                    try:
                        alerts = json.loads(alerts_raw)
                    except (json.JSONDecodeError, TypeError):
                        alerts = []

                    if alerts:
                        # Show most recent at bottom
                        for alert in alerts:
                            print(format_alert_line(alert))
                    else:
                        print(f"\n  {GREEN}No alerts. All clear.{RESET}")
                else:
                    print(f"\n  {GREEN}No alerts. All clear.{RESET}")

            print(f"\n  {DIM}Press Ctrl+C to exit{RESET}")
            time.sleep(0.5)

    except KeyboardInterrupt:
        print(f"\n{RESET}IDS Monitor stopped.")


if __name__ == "__main__":
    main()
