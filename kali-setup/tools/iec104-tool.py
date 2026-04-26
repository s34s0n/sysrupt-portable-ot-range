#!/usr/bin/env python3
"""IEC 60870-5-104 Protocol Explorer

Options:
  -t, --target    Target IP address (required)
  -p, --port      Target port (default: 2404)
  -c, --command   Command: scan, read, control
  --ioa           Information Object Address for control (e.g. 400)
  --value         Value for control: on/off, open/close, 1/0
  -h, --help      Show this help

IEC 60870-5-104 (IEC 104):
  Used in power grids, substations, energy SCADA.
  Default port: 2404. No authentication by default.
  Data organized by IOA (Information Object Address).

Object Types:
  M_SP_NA_1    Single-point status (breaker open/closed)
  M_ME_NC_1    Measured value (voltage, current, frequency)
  C_SC_NA_1    Single command (control a breaker)
"""

import argparse
import sys
import time


def _check_c104():
    """Check if c104 library is available."""
    try:
        import c104
        return True
    except ImportError:
        print("[-] Error: c104 library not installed.")
        print("    Install: pip install c104 --break-system-packages")
        return False


def cmd_scan(args):
    """Scan for IEC 104 station and list available points."""
    if not _check_c104():
        return
    import c104

    print("[*] Scanning %s:%d for IEC 104 station..." % (args.target, args.port))
    print()

    client = c104.Client(tick_rate_ms=500)
    conn = client.add_connection(ip=args.target, port=args.port, init=c104.Init.ALL)
    station = conn.add_station(common_address=1)

    # Add common monitoring points
    points = {}
    sp_ioas = [100, 101, 102, 103, 104]
    sp_names = ["Main Breaker", "Bus Tie", "Feeder A", "Feeder B", "Earth Switch"]
    for ioa, name in zip(sp_ioas, sp_names):
        points[ioa] = {"name": name, "type": "Status", "point": station.add_point(io_address=ioa, type=c104.Type.M_SP_NA_1)}

    me_ioas = [300, 301, 302, 303, 304, 305]
    me_names = ["Voltage", "Current", "Active Power", "Reactive Power", "Frequency", "Power Factor"]
    me_units = ["V", "A", "W", "VAR", "Hz", ""]
    for ioa, name, unit in zip(me_ioas, me_names, me_units):
        points[ioa] = {"name": name, "type": "Measurement", "unit": unit, "point": station.add_point(io_address=ioa, type=c104.Type.M_ME_NC_1)}

    client.start()
    time.sleep(3)

    if not conn.is_connected:
        print("[-] Could not connect to %s:%d" % (args.target, args.port))
        client.stop()
        return

    print("[+] IEC 104 station detected at %s:%d" % (args.target, args.port))
    print("    Common Address: 1")
    print("    No authentication required!")
    print()

    print("    === STATUS POINTS (M_SP_NA_1) ===")
    for ioa in sp_ioas:
        p = points[ioa]
        val = p["point"].value
        state = "CLOSED" if val else "OPEN"
        color = state
        print("    IOA %-4d %-15s %s" % (ioa, p["name"], state))

    print()
    print("    === MEASUREMENTS (M_ME_NC_1) ===")
    for ioa in me_ioas:
        p = points[ioa]
        val = p["point"].value
        if val is not None:
            print("    IOA %-4d %-15s %.2f %s" % (ioa, p["name"], val, p.get("unit", "")))

    print()
    print("    === COMMAND POINTS (C_SC_NA_1) ===")
    print("    IOA 400  Main Breaker Cmd")
    print("    IOA 401  Bus Tie Cmd")
    print("    IOA 402  Feeder A Cmd")
    print("    IOA 403  Feeder B Cmd")
    print()
    print("[+] Use -c read to refresh values")
    print("    Use -c control --ioa <n> --value <on/off> to send commands")

    client.stop()


def cmd_read(args):
    """Read all data points from the station."""
    if not _check_c104():
        return
    import c104

    print("[*] Reading data from %s:%d..." % (args.target, args.port))
    print()

    client = c104.Client(tick_rate_ms=500)
    conn = client.add_connection(ip=args.target, port=args.port, init=c104.Init.ALL)
    station = conn.add_station(common_address=1)

    sp_points = []
    for ioa in [100, 101, 102, 103, 104]:
        sp_points.append((ioa, station.add_point(io_address=ioa, type=c104.Type.M_SP_NA_1)))

    me_points = []
    me_info = [(300, "Voltage", "V"), (301, "Current", "A"), (302, "Active Power", "W"),
               (303, "Reactive Power", "VAR"), (304, "Frequency", "Hz"), (305, "Power Factor", "")]
    for ioa, name, unit in me_info:
        me_points.append((ioa, name, unit, station.add_point(io_address=ioa, type=c104.Type.M_ME_NC_1)))

    client.start()
    time.sleep(3)

    if not conn.is_connected:
        print("[-] Could not connect to %s:%d" % (args.target, args.port))
        client.stop()
        return

    sp_names = ["Main Breaker", "Bus Tie", "Feeder A", "Feeder B", "Earth Switch"]
    print("    === BREAKER STATUS ===")
    for (ioa, pt), name in zip(sp_points, sp_names):
        state = "CLOSED" if pt.value else "OPEN"
        print("    IOA %-4d %-15s %s" % (ioa, name, state))

    print()
    print("    === MEASUREMENTS ===")
    for ioa, name, unit, pt in me_points:
        if pt.value is not None:
            print("    IOA %-4d %-15s %8.2f %s" % (ioa, name, pt.value, unit))

    client.stop()


def cmd_control(args):
    """Send a control command to an IOA."""
    if not _check_c104():
        return
    import c104

    if args.ioa is None:
        print("[-] Error: --ioa is required for control command")
        sys.exit(1)
    if args.value is None:
        print("[-] Error: --value is required (on/off, open/close, 1/0)")
        sys.exit(1)

    ioa = args.ioa
    val_str = args.value.lower()
    if val_str in ("on", "close", "closed", "1", "true"):
        val = True
    elif val_str in ("off", "open", "0", "false", "trip"):
        val = False
    else:
        print("[-] Invalid value: %s (use on/off, open/close, 1/0)" % args.value)
        sys.exit(1)

    print("[*] Sending command to %s:%d..." % (args.target, args.port))
    print("    IOA: %d" % ioa)
    print("    Value: %s (%s)" % (val, "CLOSE" if val else "OPEN/TRIP"))
    print()

    client = c104.Client(tick_rate_ms=500)
    conn = client.add_connection(ip=args.target, port=args.port, init=c104.Init.ALL)
    station = conn.add_station(common_address=1)

    # Monitor point to verify
    sp = station.add_point(io_address=ioa - 300 if ioa >= 400 else ioa, type=c104.Type.M_SP_NA_1)
    cmd = station.add_point(io_address=ioa, type=c104.Type.C_SC_NA_1)

    client.start()
    time.sleep(3)

    if not conn.is_connected:
        print("[-] Could not connect to %s:%d" % (args.target, args.port))
        client.stop()
        return

    print("    Before: %s" % ("CLOSED" if sp.value else "OPEN"))

    cmd.value = val
    result = cmd.transmit(cause=c104.Cot.ACTIVATION)
    print("    Command sent: %s" % ("OK" if result else "FAILED"))
    time.sleep(2)

    print("    After:  %s" % ("CLOSED" if sp.value else "OPEN"))
    print()

    if result:
        print("[+] Command accepted - no authentication!")
    else:
        print("[-] Command rejected by outstation")

    client.stop()


def main():
    parser = argparse.ArgumentParser(
        description="IEC 60870-5-104 Protocol Explorer",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""IEC 60870-5-104 (IEC 104):
  Used in power grids, substations, energy SCADA.
  Default port: 2404. No authentication by default.

Data Types:
  M_SP_NA_1    Single-point status (on/off, open/closed)
  M_ME_NC_1    Measured value (voltage, current, frequency)
  C_SC_NA_1    Single command (trip/close breaker)"""
    )
    parser.add_argument("-t", "--target", required=True, help="Target IP address")
    parser.add_argument("-p", "--port", type=int, default=2404, help="Target port (default: 2404)")
    parser.add_argument("-c", "--command", required=True, choices=["scan", "read", "control"],
                        help="Command to execute")
    parser.add_argument("--ioa", type=int, default=None, help="Information Object Address for control")
    parser.add_argument("--value", default=None,
                        help="Value for control: on/off, open/close, trip, 1/0")

    args = parser.parse_args()

    if args.command == "scan":
        cmd_scan(args)
    elif args.command == "read":
        cmd_read(args)
    elif args.command == "control":
        cmd_control(args)


if __name__ == "__main__":
    main()
