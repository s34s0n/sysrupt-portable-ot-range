#!/usr/bin/env python3
"""EtherNet/IP (CIP) Protocol Explorer

Options:
  -t, --target    Target IP address (required)
  -p, --port      Target port (default: 44818)
  -c, --command   Command: scan, read, write
  --tag           Tag name for read/write (e.g. OUTLET_PRESSURE)
  --index         Array index (default: 0)
  --value         Value for write command (integer)
  -h, --help      Show this help

EtherNet/IP (CIP - Common Industrial Protocol):
  Used by Rockwell/Allen-Bradley PLCs.
  Default port: 44818. No authentication by default.
"""

import argparse
import subprocess
import sys
import os


ENIP_PORT = 44818

# Common ICS tags that might exist on a PLC
COMMON_TAGS = [
    "OUTLET_PRESSURE", "BOOSTER_FLOW", "RESERVOIR_LEVEL",
    "DIST_TEMP", "SYSTEM_STATUS", "OUTLET_VALVE_CMD",
    "BOOSTER_PUMP_SPEED", "PRESSURE_SP", "MODE_SELECT",
    "ALARM_ENABLE", "ALARM_THRESHOLD",
    "PID_OUTPUT", "PID_SETPOINT", "PID_MODE",
    "PUMP_SPEED", "VALVE_CMD", "FLOW_RATE",
]


def _run_cpppo(target, port, operations, timeout=5):
    """Run cpppo client and return output."""
    cmd = [
        sys.executable, "-m", "cpppo.server.enip.client",
        "--print",
        "--address", "%s:%d" % (target, port),
    ] + operations

    env = os.environ.copy()
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, env=env,
        )
        return result.stdout.strip(), result.stderr.strip(), result.returncode
    except subprocess.TimeoutExpired:
        return "", "Connection timed out", 1
    except FileNotFoundError:
        return "", "cpppo not installed. Run: pip install cpppo --break-system-packages", 1


def cmd_scan(args):
    """Scan for EtherNet/IP service and enumerate tags."""
    print("[*] Scanning %s:%d for EtherNet/IP service..." % (args.target, args.port))
    print()

    # Try to read a common tag to verify connection
    stdout, stderr, rc = _run_cpppo(args.target, args.port, ["SYSTEM_STATUS"])
    if rc != 0 and "timed out" in stderr.lower():
        print("[-] No response from %s:%d" % (args.target, args.port))
        return

    print("[+] EtherNet/IP service detected at %s:%d" % (args.target, args.port))
    print("    No authentication required!")
    print()

    # Enumerate known tags
    print("[*] Enumerating tags...")
    print()
    found = []
    for tag in COMMON_TAGS:
        stdout, stderr, rc = _run_cpppo(args.target, args.port, [tag], timeout=3)
        if rc == 0 and stdout and "OK" in stdout:
            # Parse value from output like: "TAG              == [420]: 'OK'"
            val = ""
            if "==" in stdout:
                try:
                    val = stdout.split("==")[1].split("]")[0].strip(" [")
                except Exception:
                    pass
            found.append((tag, val))
            print("    [+] %-25s = %s" % (tag, val))

    print()
    if found:
        print("[+] Found %d tags." % len(found))
        print("    Use -c read --tag <name> to read a specific tag.")
        print("    Use -c write --tag <name> --value <n> to write.")
    else:
        print("[-] No known tags found. Service may use custom tag names.")


def cmd_read(args):
    """Read a tag value."""
    if not args.tag:
        print("[-] Error: --tag is required for read command")
        sys.exit(1)

    tag = args.tag
    idx = args.index
    operation = "%s[%d]" % (tag, idx)

    print("[*] Reading %s from %s:%d..." % (operation, args.target, args.port))
    print()

    stdout, stderr, rc = _run_cpppo(args.target, args.port, [operation])

    if rc != 0:
        if "timed out" in stderr.lower():
            print("[-] Connection timed out")
        else:
            print("[-] Error reading tag: %s" % stderr.split("\n")[-1] if stderr else "unknown")
        return

    if stdout:
        print("    %s" % stdout)
    else:
        print("[-] No response")


def cmd_write(args):
    """Write a value to a tag."""
    if not args.tag:
        print("[-] Error: --tag is required for write command")
        sys.exit(1)
    if args.value is None:
        print("[-] Error: --value is required for write command")
        sys.exit(1)

    tag = args.tag
    idx = args.index
    val = int(args.value)
    operation = "%s[%d]=%d" % (tag, idx, val)

    print("[*] Writing %s[%d] = %d on %s:%d..." % (tag, idx, val, args.target, args.port))
    print()

    stdout, stderr, rc = _run_cpppo(args.target, args.port, [operation])

    if rc != 0:
        if "timed out" in stderr.lower():
            print("[-] Connection timed out")
        else:
            print("[-] Error writing tag: %s" % stderr.split("\n")[-1] if stderr else "unknown")
        return

    if stdout:
        print("    %s" % stdout)
        print()
        print("[+] Write accepted - no authentication!")
    else:
        print("[-] No response")


def main():
    parser = argparse.ArgumentParser(
        description="EtherNet/IP (CIP) Protocol Explorer",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""EtherNet/IP (CIP - Common Industrial Protocol):
  Used by Rockwell/Allen-Bradley PLCs.
  Default port: 44818. No authentication by default.
  Data organized as named Tags (like PLC variables)."""
    )
    parser.add_argument("-t", "--target", required=True, help="Target IP address")
    parser.add_argument("-p", "--port", type=int, default=ENIP_PORT, help="Target port (default: 44818)")
    parser.add_argument("-c", "--command", required=True, choices=["scan", "read", "write"],
                        help="Command to execute")
    parser.add_argument("--tag", default=None, help="Tag name (e.g. OUTLET_PRESSURE)")
    parser.add_argument("--index", type=int, default=0, help="Array index (default: 0)")
    parser.add_argument("--value", default=None, help="Value for write command (integer)")

    args = parser.parse_args()

    if args.command == "scan":
        cmd_scan(args)
    elif args.command == "read":
        cmd_read(args)
    elif args.command == "write":
        cmd_write(args)


if __name__ == "__main__":
    main()
