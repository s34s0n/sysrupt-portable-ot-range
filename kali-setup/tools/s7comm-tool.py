#!/usr/bin/env python3
"""S7comm Protocol Explorer

Options:
  -t, --target    Target IP address (required)
  -p, --port      Target port (default: 102)
  -c, --command   Command: scan, read, write
  --db            Data block number (e.g. 1, 2, 99)
  --offset        Byte offset within DB (default: 0)
  --size          Number of bytes to read (default: 32)
  --value         Value for write (integer, written as 16-bit big-endian)
  --bit           Bit number for single-bit write (0-7)
  --bit-value     Bit value: on/off, 1/0
  -h, --help      Show this help

S7comm (Siemens S7 Communication):
  Used by Siemens S7-300/400/1200/1500 PLCs.
  Default port: 102 (ISO-on-TCP). No authentication by default.
  Data organized in Data Blocks (DB1, DB2, etc).
"""

import argparse
import struct
import sys


def _check_snap7():
    try:
        import snap7
        return True
    except ImportError:
        print("[-] Error: snap7 library not installed.")
        print("    Install: pip install python-snap7 --break-system-packages")
        print("    Also: sudo apt install libsnap7-dev libsnap7-1")
        return False


def _connect(target, port):
    import snap7
    client = snap7.client.Client()
    try:
        client.connect(target, 0, 1, port)
        return client
    except Exception as e:
        print("[-] Could not connect to %s:%d - %s" % (target, port, e))
        return None


def cmd_scan(args):
    """Scan for S7 PLC and enumerate data blocks."""
    if not _check_snap7():
        return

    print("[*] Scanning %s:%d for S7comm PLC..." % (args.target, args.port))
    print()

    client = _connect(args.target, args.port)
    if not client:
        return

    print("[+] S7comm PLC detected at %s:%d" % (args.target, args.port))
    print("    No authentication required!")
    print()

    # Try to read common data blocks
    common_dbs = [1, 2, 3, 10, 50, 99, 100]
    found_dbs = []

    print("[*] Enumerating data blocks...")
    print()
    for db in common_dbs:
        try:
            data = client.db_read(db, 0, 2)
            if data:
                found_dbs.append(db)
                print("    [+] DB%-4d accessible (%d+ bytes)" % (db, len(data)))
        except Exception:
            pass

    if found_dbs:
        print()
        print("[+] Found %d data blocks." % len(found_dbs))
        print("    Use -c read --db <n> to read a data block.")
        print("    Use -c write --db <n> --offset <n> --value <n> to write.")
    else:
        print("    [-] No common data blocks found.")

    # Read each found DB with more detail
    for db in found_dbs:
        try:
            size = 32
            data = client.db_read(db, 0, size)
            print()
            print("    === DB%d (first %d bytes) ===" % (db, size))
            for i in range(0, len(data), 16):
                hex_part = " ".join("%02X" % data[j] for j in range(i, min(i + 16, len(data))))
                ascii_part = "".join(chr(data[j]) if 32 <= data[j] < 127 else "." for j in range(i, min(i + 16, len(data))))
                print("    %04X: %-48s  %s" % (i, hex_part, ascii_part))
        except Exception:
            pass

    client.disconnect()


def cmd_read(args):
    """Read a data block."""
    if not _check_snap7():
        return
    if args.db is None:
        print("[-] Error: --db is required for read command")
        sys.exit(1)

    db = args.db
    offset = args.offset
    size = args.size

    print("[*] Reading DB%d offset %d size %d from %s:%d..." % (db, offset, size, args.target, args.port))
    print()

    client = _connect(args.target, args.port)
    if not client:
        return

    try:
        data = client.db_read(db, offset, size)
    except Exception as e:
        print("[-] Error reading DB%d: %s" % (db, e))
        client.disconnect()
        return

    # Hex dump
    print("    === DB%d (%d bytes from offset %d) ===" % (db, len(data), offset))
    for i in range(0, len(data), 16):
        abs_off = offset + i
        hex_part = " ".join("%02X" % data[j] for j in range(i, min(i + 16, len(data))))
        ascii_part = "".join(chr(data[j]) if 32 <= data[j] < 127 else "." for j in range(i, min(i + 16, len(data))))
        print("    %04X: %-48s  %s" % (abs_off, hex_part, ascii_part))

    # Try to decode common structures
    print()
    print("    === DECODED VALUES ===")
    for i in range(0, min(len(data), size), 2):
        abs_off = offset + i
        if i + 1 < len(data):
            val_u16 = struct.unpack_from(">H", data, i)[0]
            val_s16 = struct.unpack_from(">h", data, i)[0]

            # Check for bits in first byte
            if i == 0 and db in (1,):
                byte0 = data[0]
                bits = []
                for b in range(8):
                    if byte0 & (1 << b):
                        bits.append("bit%d=1" % b)
                if bits:
                    print("    Byte 0 bits: %s (0x%02X = %s)" % (bin(byte0), byte0, ", ".join(bits)))
            else:
                if val_u16 != 0:
                    print("    Offset %-3d: %5d (0x%04X)" % (abs_off, val_u16, val_u16))

    client.disconnect()


def cmd_write(args):
    """Write a value to a data block."""
    if not _check_snap7():
        return
    if args.db is None:
        print("[-] Error: --db is required for write command")
        sys.exit(1)

    db = args.db
    offset = args.offset

    print("[*] Connecting to %s:%d..." % (args.target, args.port))
    print()

    client = _connect(args.target, args.port)
    if not client:
        return

    # Bit write
    if args.bit is not None and args.bit_value is not None:
        bit = args.bit
        val = args.bit_value.lower() in ("1", "on", "true")
        try:
            current = client.db_read(db, offset, 1)
            if val:
                current[0] |= (1 << bit)
            else:
                current[0] &= ~(1 << bit)
            client.db_write(db, offset, current)
            print("    DB%d byte %d bit %d = %s - write accepted!" % (db, offset, bit, "ON" if val else "OFF"))
            print()
            print("[+] No authentication required!")
        except Exception as e:
            print("    [-] Write failed: %s" % e)
        client.disconnect()
        return

    # Value write (16-bit big-endian)
    if args.value is None:
        print("[-] Error: --value or --bit/--bit-value required for write")
        sys.exit(1)

    value = int(args.value)
    buf = bytearray(2)
    struct.pack_into(">H", buf, 0, value & 0xFFFF)

    try:
        client.db_write(db, offset, buf)
        print("    DB%d offset %d = %d (0x%04X) - write accepted!" % (db, offset, value, value & 0xFFFF))
        print()
        print("[+] No authentication required!")
    except Exception as e:
        print("    [-] Write failed: %s" % e)

    client.disconnect()


def main():
    parser = argparse.ArgumentParser(
        description="S7comm Protocol Explorer",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""S7comm (Siemens S7 Communication):
  Used by Siemens S7-300/400/1200/1500 PLCs.
  Default port: 102 (ISO-on-TCP). No authentication by default.
  Data organized in Data Blocks (DB1=status, DB2=setpoints, etc)."""
    )
    parser.add_argument("-t", "--target", required=True, help="Target IP address")
    parser.add_argument("-p", "--port", type=int, default=102, help="Target port (default: 102)")
    parser.add_argument("-c", "--command", required=True, choices=["scan", "read", "write"],
                        help="Command to execute")
    parser.add_argument("--db", type=int, default=None, help="Data block number (e.g. 1, 2, 99)")
    parser.add_argument("--offset", type=int, default=0, help="Byte offset within DB (default: 0)")
    parser.add_argument("--size", type=int, default=32, help="Bytes to read (default: 32)")
    parser.add_argument("--value", default=None, help="Value for write (16-bit integer)")
    parser.add_argument("--bit", type=int, default=None, help="Bit number for single-bit write (0-7)")
    parser.add_argument("--bit-value", default=None, help="Bit value: on/off, 1/0")

    args = parser.parse_args()

    if args.command == "scan":
        cmd_scan(args)
    elif args.command == "read":
        cmd_read(args)
    elif args.command == "write":
        cmd_write(args)


if __name__ == "__main__":
    main()
