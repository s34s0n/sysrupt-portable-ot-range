#!/usr/bin/env python3
"""BACnet/IP Protocol Explorer

Options:
  -t, --target      Target IP address (required)
  -p, --port        Target port (default: 47808)
  -c, --command     Command: scan, list, read, read-all
  --type            Object type for read: AI, AO, AV, BI, BO, BV
  --instance        Object instance number for read
  --property        Property ID for read (default: 85=Present-Value, 28=Description, 77=Object-Name)
  -h, --help        Show this help

BACnet/IP (Building Automation and Control):
  Used in HVAC, lighting, access control, fire systems.
  Default port: 47808 (UDP). No authentication by default.

Object Types:
  AI   Analog Input    (sensors - temperature, pressure, flow)
  AO   Analog Output   (actuators - valve position, speed)
  AV   Analog Value    (config - setpoints, parameters)
  BI   Binary Input    (digital sensors - on/off, open/closed)
  BO   Binary Output   (digital actuators - start/stop)
  BV   Binary Value    (config - enable/disable)
"""

import argparse
import socket
import struct
import sys


BACNET_PORT = 47808

TYPE_MAP = {
    "AI": 0, "AO": 1, "AV": 2, "BI": 3, "BO": 4, "BV": 5,
}

PROPERTY_NAMES = {
    28: "Description",
    77: "Object-Name",
    85: "Present-Value",
    36: "Event-State",
    103: "Reliability",
    111: "Status-Flags",
    117: "Units",
}


def build_read_property(obj_type, instance, property_id):
    bvll_type = 0x81
    bvll_func = 0x0a
    npdu = bytes([0x01, 0x04])
    invoke_id = 0x01
    service = 0x0c
    obj_id = (obj_type << 22) | (instance & 0x3FFFFF)
    tag0 = bytes([0x0C]) + struct.pack(">I", obj_id)
    if property_id < 256:
        tag1 = bytes([0x19, property_id])
    else:
        tag1 = bytes([0x1A]) + struct.pack(">H", property_id)
    apdu = bytes([0x00, 0x04, invoke_id, service]) + tag0 + tag1
    payload = npdu + apdu
    length = 4 + len(payload)
    bvll = bytes([bvll_type, bvll_func]) + struct.pack(">H", length)
    return bvll + payload


def send_recv(ip, port, packet, timeout=3):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(timeout)
    s.sendto(packet, (ip, port))
    try:
        data, addr = s.recvfrom(4096)
        return data
    except socket.timeout:
        return None
    finally:
        s.close()


def parse_value(resp):
    """Extract value from BACnet ReadProperty response."""
    if not resp or len(resp) < 12:
        return None
    if len(resp) > 7 and resp[7] == 0x50:
        return None
    try:
        for j in range(12, len(resp)):
            tag = resp[j]
            tag_class = (tag >> 3) & 0x01
            if tag_class == 0:
                tag_num = (tag >> 4) & 0x0F
                tag_len = tag & 0x07
                if tag_num == 4 and j + 5 <= len(resp):
                    return "%.4f" % struct.unpack(">f", resp[j+1:j+5])[0]
                elif tag_num == 7 and j + 1 < len(resp):
                    str_len = resp[j+1]
                    if j + 2 + str_len <= len(resp):
                        return resp[j+3:j+2+str_len].decode("utf-8", errors="replace")
                elif tag_num == 1:
                    return str(bool(resp[j+1] if j+1 < len(resp) else 0))
                elif tag_num == 2 and tag_len > 0:
                    return str(int.from_bytes(resp[j+1:j+1+tag_len], "big"))
                elif tag_num == 9 and tag_len > 0:
                    return str(int.from_bytes(resp[j+1:j+1+tag_len], "big"))
    except Exception:
        pass
    return None


def cmd_scan(args):
    print("[*] Sending BACnet WhoIs to %s:%d..." % (args.target, args.port))
    print()
    whois = bytes([0x81, 0x0b, 0x00, 0x0c, 0x01, 0x20, 0xff, 0xff, 0x00, 0xff, 0x10, 0x08])
    resp = send_recv(args.target, args.port, whois)
    if resp:
        print("[+] Device responded!")
        print("    Raw response: %s" % resp.hex()[:60])
        if len(resp) > 12:
            try:
                for i in range(len(resp) - 4):
                    if resp[i] == 0xC4:
                        obj_id = struct.unpack(">I", resp[i+1:i+5])[0]
                        dev_type = (obj_id >> 22) & 0x3FF
                        dev_instance = obj_id & 0x3FFFFF
                        if dev_type == 8:
                            print("    Device ID: %d" % dev_instance)
                        break
            except Exception:
                pass
        print()
        print("[+] BACnet device confirmed at %s" % args.target)
        print("    No authentication required!")
    else:
        print("[-] No response from %s:%d" % (args.target, args.port))


def cmd_list(args):
    print("[*] Enumerating BACnet objects on %s..." % args.target)
    print()
    found = []
    for type_name, type_id in [("AI", 0), ("AO", 1), ("AV", 2), ("BI", 3), ("BO", 4), ("BV", 5)]:
        for instance in list(range(0, 10)) + [50, 99, 100, 101, 200]:
            pkt = build_read_property(type_id, instance, 85)
            resp = send_recv(args.target, args.port, pkt, timeout=1)
            if resp and len(resp) > 12 and resp[7] != 0x50:
                val = parse_value(resp) or "(readable)"
                found.append((type_name, instance))
                sys.stdout.write("    [+] %s:%-3d = %s\n" % (type_name, instance, val))
                sys.stdout.flush()
    print()
    if found:
        print("[+] Found %d objects." % len(found))
        print("    Tip: Use -c read with --type and --instance to inspect objects.")
        print("    Tip: Try --property 28 to read the Description field.")
    else:
        print("[-] No objects found")


def cmd_read(args):
    if args.type is None or args.instance is None:
        print("[-] Error: --type and --instance are required for read command")
        sys.exit(1)
    type_str = args.type.upper()
    if type_str not in TYPE_MAP:
        print("[-] Unknown type: %s (use AI, AO, AV, BI, BO, BV)" % type_str)
        sys.exit(1)
    type_id = TYPE_MAP[type_str]
    prop = args.property
    prop_name = PROPERTY_NAMES.get(prop, "Property-%d" % prop)

    print("[*] Reading %s:%d %s from %s..." % (type_str, args.instance, prop_name, args.target))
    print()
    pkt = build_read_property(type_id, args.instance, prop)
    resp = send_recv(args.target, args.port, pkt)
    if resp:
        if len(resp) > 7 and resp[7] == 0x50:
            print("[-] Error: object or property not found")
            return
        value = parse_value(resp)
        if value:
            print("    %s:%d %s = %s" % (type_str, args.instance, prop_name, value))
        else:
            print("    Raw response: %s" % resp[12:].hex())
    else:
        print("[-] No response")


def cmd_read_all(args):
    if args.type is None or args.instance is None:
        print("[-] Error: --type and --instance are required for read-all command")
        sys.exit(1)
    type_str = args.type.upper()
    if type_str not in TYPE_MAP:
        print("[-] Unknown type: %s" % type_str)
        sys.exit(1)
    type_id = TYPE_MAP[type_str]

    print("[*] Reading all properties of %s:%d from %s..." % (type_str, args.instance, args.target))
    print()
    for prop_id, prop_name in sorted(PROPERTY_NAMES.items()):
        pkt = build_read_property(type_id, args.instance, prop_id)
        resp = send_recv(args.target, args.port, pkt, timeout=1)
        if resp and len(resp) > 7 and resp[7] != 0x50:
            value = parse_value(resp)
            if value:
                print("    %-20s = %s" % (prop_name, value))


def main():
    parser = argparse.ArgumentParser(
        description="BACnet/IP Protocol Explorer",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Object Types:
  AI   Analog Input    (sensors)       AO   Analog Output   (actuators)
  AV   Analog Value    (config)        BI   Binary Input    (digital in)
  BO   Binary Output   (digital out)   BV   Binary Value    (digital config)

BACnet/IP: Used in HVAC, lighting, access control, fire systems.
Default port: 47808 (UDP). No authentication by default."""
    )
    parser.add_argument("-t", "--target", required=True, help="Target IP address")
    parser.add_argument("-p", "--port", type=int, default=BACNET_PORT, help="Target port (default: 47808)")
    parser.add_argument("-c", "--command", required=True, choices=["scan", "list", "read", "read-all"],
                        help="Command to execute")
    parser.add_argument("--type", default=None, help="Object type: AI, AO, AV, BI, BO, BV")
    parser.add_argument("--instance", type=int, default=None, help="Object instance number")
    parser.add_argument("--property", type=int, default=85,
                        help="Property ID (default: 85=Present-Value, 28=Description, 77=Object-Name)")

    args = parser.parse_args()

    if args.command == "scan":
        cmd_scan(args)
    elif args.command == "list":
        cmd_list(args)
    elif args.command == "read":
        cmd_read(args)
    elif args.command == "read-all":
        cmd_read_all(args)


if __name__ == "__main__":
    main()
