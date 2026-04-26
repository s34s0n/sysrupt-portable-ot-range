#!/usr/bin/env python3
"""Modbus TCP Protocol Explorer

Options:
  -t, --target    Target IP address (required)
  -p, --port      Target port (default: 502)
  -c, --command   Command: scan, read, write
  --register      Register address for read/write
  --count         Number of registers to read (default: 1)
  --value         Value for write command (integer)
  --type          Register type: holding, coil, input, discrete (default: holding)
  -h, --help      Show this help

Modbus TCP:
  Used in PLCs, RTUs, chemical dosing, pump controllers.
  Default port: 502. No authentication by default.
  Data organized as numbered registers (0-65535).

Register Types:
  holding    Read/Write registers (setpoints, control params)
  coil       Read/Write digital outputs (on/off, pump run)
  input      Read-only analog inputs (sensor values)
  discrete   Read-only digital inputs (switch states)
"""

import argparse
import sys


def _check_pymodbus():
    try:
        from pymodbus.client import ModbusTcpClient
        return True
    except ImportError:
        print("[-] Error: pymodbus not installed.")
        print("    Install: pip install pymodbus --break-system-packages")
        return False


def _connect(target, port):
    from pymodbus.client import ModbusTcpClient
    client = ModbusTcpClient(host=target, port=port, timeout=5)
    if not client.connect():
        print("[-] Could not connect to %s:%d" % (target, port))
        return None
    return client


def cmd_scan(args):
    """Scan for Modbus device and enumerate registers."""
    if not _check_pymodbus():
        return

    print("[*] Scanning %s:%d for Modbus TCP device..." % (args.target, args.port))
    print()

    client = _connect(args.target, args.port)
    if not client:
        return

    print("[+] Modbus TCP device detected at %s:%d" % (args.target, args.port))
    print("    No authentication required!")
    print()

    # Read holding registers
    print("    === HOLDING REGISTERS ===")
    rr = client.read_holding_registers(0, count=16)
    if not rr.isError():
        for i, val in enumerate(rr.registers):
            print("    HR %-4d = %5d  (0x%04X)" % (i, val, val))
    else:
        print("    [-] Could not read holding registers")

    print()

    # Read coils
    print("    === COILS (Digital Outputs) ===")
    cr = client.read_coils(0, count=7)
    if not cr.isError():
        for i, val in enumerate(cr.bits[:7]):
            print("    Coil %-3d = %s" % (i, "ON" if val else "OFF"))
    else:
        print("    [-] Could not read coils")

    print()

    # Read input registers
    print("    === INPUT REGISTERS (Sensors) ===")
    ir = client.read_input_registers(0, count=4)
    if not ir.isError():
        for i, val in enumerate(ir.registers):
            print("    IR %-4d = %5d  (0x%04X)" % (i, val, val))
    else:
        print("    [-] Could not read input registers")

    print()
    print("[+] Use -c read --register <n> --count <n> for specific registers")
    print("    Use -c write --register <n> --value <n> to write")

    client.close()


def cmd_read(args):
    """Read registers from the device."""
    if not _check_pymodbus():
        return

    reg = args.register if args.register is not None else 0
    count = args.count
    reg_type = args.type

    print("[*] Reading %s registers %d-%d from %s:%d..." % (reg_type, reg, reg + count - 1, args.target, args.port))
    print()

    client = _connect(args.target, args.port)
    if not client:
        return

    if reg_type == "holding":
        rr = client.read_holding_registers(reg, count=count)
        if not rr.isError():
            for i, val in enumerate(rr.registers):
                print("    HR %-4d = %5d  (0x%04X)" % (reg + i, val, val))
        else:
            print("    [-] Error: %s" % rr)

    elif reg_type == "coil":
        cr = client.read_coils(reg, count=count)
        if not cr.isError():
            for i, val in enumerate(cr.bits[:count]):
                print("    Coil %-3d = %s" % (reg + i, "ON" if val else "OFF"))
        else:
            print("    [-] Error: %s" % cr)

    elif reg_type == "input":
        ir = client.read_input_registers(reg, count=count)
        if not ir.isError():
            for i, val in enumerate(ir.registers):
                print("    IR %-4d = %5d  (0x%04X)" % (reg + i, val, val))
        else:
            print("    [-] Error: %s" % ir)

    elif reg_type == "discrete":
        dr = client.read_discrete_inputs(reg, count=count)
        if not dr.isError():
            for i, val in enumerate(dr.bits[:count]):
                print("    DI %-3d = %s" % (reg + i, "ON" if val else "OFF"))
        else:
            print("    [-] Error: %s" % dr)

    client.close()


def cmd_write(args):
    """Write a value to a register."""
    if not _check_pymodbus():
        return

    if args.register is None:
        print("[-] Error: --register is required for write command")
        sys.exit(1)
    if args.value is None:
        print("[-] Error: --value is required for write command")
        sys.exit(1)

    reg = args.register
    val = int(args.value)
    reg_type = args.type

    print("[*] Writing %s register %d = %d on %s:%d..." % (reg_type, reg, val, args.target, args.port))
    print()

    client = _connect(args.target, args.port)
    if not client:
        return

    if reg_type == "holding":
        result = client.write_register(reg, val)
        if not result.isError():
            print("    HR %d = %d - write accepted!" % (reg, val))
            print()
            print("[+] No authentication required!")
        else:
            print("    [-] Write failed: %s" % result)

    elif reg_type == "coil":
        result = client.write_coil(reg, bool(val))
        if not result.isError():
            print("    Coil %d = %s - write accepted!" % (reg, "ON" if val else "OFF"))
            print()
            print("[+] No authentication required!")
        else:
            print("    [-] Write failed: %s" % result)
    else:
        print("    [-] Cannot write to %s registers (read-only)" % reg_type)

    client.close()


def main():
    parser = argparse.ArgumentParser(
        description="Modbus TCP Protocol Explorer",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Modbus TCP:
  Used in PLCs, RTUs, chemical dosing, pump controllers.
  Default port: 502. No authentication by default.

Register Types:
  holding    Read/Write (setpoints, PID params, speeds)
  coil       Read/Write digital (pump on/off, valve open/close)
  input      Read-only analog (sensor readings)
  discrete   Read-only digital (switch states)"""
    )
    parser.add_argument("-t", "--target", required=True, help="Target IP address")
    parser.add_argument("-p", "--port", type=int, default=502, help="Target port (default: 502)")
    parser.add_argument("-c", "--command", required=True, choices=["scan", "read", "write"],
                        help="Command to execute")
    parser.add_argument("--register", type=int, default=None, help="Register address")
    parser.add_argument("--count", type=int, default=1, help="Number of registers to read (default: 1)")
    parser.add_argument("--value", default=None, help="Value for write command")
    parser.add_argument("--type", default="holding", choices=["holding", "coil", "input", "discrete"],
                        help="Register type (default: holding)")

    args = parser.parse_args()

    if args.command == "scan":
        cmd_scan(args)
    elif args.command == "read":
        cmd_read(args)
    elif args.command == "write":
        cmd_write(args)


if __name__ == "__main__":
    main()
