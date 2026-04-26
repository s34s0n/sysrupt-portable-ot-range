"""PLC-3 Filtration - DNP3 Outstation (minimal raw-socket implementation).

Speaks enough DNP3 (IEEE 1815) link-layer and application-layer framing
to be recognised as a DNP3 outstation by standard masters and protocol
analysers. Supports integrity polls (FC1 READ) and returns Class 0 data
(binary inputs, analog inputs, counters), plus DIRECT OPERATE (FC5) for
CROB/AO control commands.

This is a teaching server, not a conformance-tested outstation.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import random
import struct
import sys
import threading
import time

# Make project root importable so "services.plc_common" resolves.
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import redis  # noqa: E402

log = logging.getLogger("plc-filtration")


# --------------------------------------------------------------------------- #
# DNP3 link-layer CRC (reflected polynomial 0xA6BC)
# --------------------------------------------------------------------------- #

def dnp3_crc(data: bytes) -> int:
    crc = 0
    for byte in data:
        crc ^= byte
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0xA6BC
            else:
                crc >>= 1
    crc ^= 0xFFFF
    return crc & 0xFFFF


def crc_append(block: bytes) -> bytes:
    c = dnp3_crc(block)
    return block + struct.pack("<H", c)


# --------------------------------------------------------------------------- #
# Frame building helpers
# --------------------------------------------------------------------------- #

def build_link_frame(ctrl: int, dest: int, src: int, user_data: bytes) -> bytes:
    """Build a full DNP3 link-layer frame including header and data CRCs."""
    length = 5 + len(user_data)  # ctrl + dest(2) + src(2) + user_data
    header = bytes([0x05, 0x64, length & 0xFF, ctrl & 0xFF]) + struct.pack("<HH", dest, src)
    frame = crc_append(header)
    # Split user_data into 16-byte chunks, each with trailing CRC.
    for i in range(0, len(user_data), 16):
        chunk = user_data[i:i + 16]
        frame += crc_append(chunk)
    return frame


def strip_link_data_crcs(data_with_crcs: bytes, user_len: int) -> bytes:
    """Given the body bytes after the link header, remove the per-16-byte CRCs."""
    out = b""
    remaining = user_len
    pos = 0
    while remaining > 0:
        chunk = min(16, remaining)
        out += data_with_crcs[pos:pos + chunk]
        pos += chunk + 2  # skip trailing CRC
        remaining -= chunk
    return out


# --------------------------------------------------------------------------- #
# DNP3 outstation
# --------------------------------------------------------------------------- #

class FiltrationDNP3:
    PLC_NAME = "PLC-3 Filtration DNP3 Outstation"
    PLC_ID = "filtration"

    OUTSTATION_ADDR = 10
    MASTER_ADDR = 1

    def __init__(self, bind_ip: str = "0.0.0.0", bind_port: int = 20000):
        self.bind_ip = bind_ip
        self.bind_port = bind_port

        # Simulated process state.
        # Binary inputs: pre-filter bypass, filter-1 running, filter-2 running,
        # backwash active, low-dp alarm, high-dp alarm, maintenance required.
        self.binary_inputs = [False, True, True, False, False, False, False]
        # Binary outputs: f1 run, f2 run, backwash valve, bypass valve, drain, led.
        self.binary_outputs = [True, True, False, False, False, False]
        # Analog inputs: dp1, dp2, dp3, dp4 (kPa*10), turbidity_ntu, chlorine_ppb, flow_lpm.
        self.analog_inputs = [250, 270, 240, 260, 50, 250, 850]
        # Analog outputs: backwash_sp, filter_rate_sp, chlorine_sp.
        self.analog_outputs = [100, 400, 500]
        # Counters: values encode ASCII message for CRC challenge.
        # Counter[0..9] = ASCII codes spelling "FILTRATION"
        # Students must: read counters → decode ASCII → calculate CRC-16-DNP → write it back
        self._crc_message = "FILTRATION"
        self.counters = [ord(c) for c in self._crc_message]
        # Expected CRC-16-DNP of "FILTRATION"
        self._expected_crc = dnp3_crc(self._crc_message.encode("ascii"))

        self._scan_count = 0
        self._connected_clients = 0
        self.running = False
        self._app_seq = 0  # outstation application sequence

        self._redis = None
        self._connect_redis()

    # ----------------------- redis ------------------------------------- #
    def _connect_redis(self):
        for host in ["127.0.0.1", "10.0.4.1", "10.0.5.1", "10.0.3.1", "10.0.2.1", "10.0.1.1"]:
            try:
                r = redis.Redis(
                    host=host,
                    port=6379,
                    socket_timeout=1,
                    socket_connect_timeout=1,
                    decode_responses=True,
                )
                r.ping()
                self._redis = r
                log.info("redis connected at %s", host)
                return
            except Exception:
                continue
        log.warning("redis unavailable - running in degraded mode")

    def _publish_state(self):
        if not self._redis:
            return
        state = {
            "plc_id": self.PLC_ID,
            "status": "running",
            "protocol": "dnp3",
            "port": self.bind_port,
            "binaries": self.binary_inputs,
            "binary_outputs": self.binary_outputs,
            "analogs": self.analog_inputs,
            "analog_outputs": self.analog_outputs,
            "counters": self.counters,
            "scan_count": self._scan_count,
            "connected_clients": self._connected_clients,
            "ts": time.time(),
        }
        try:
            pipe = self._redis.pipeline()
            pipe.set(f"plc:{self.PLC_ID}:status", "running")
            pipe.set(f"plc:{self.PLC_ID}:binaries", json.dumps(self.binary_inputs))
            pipe.set(f"plc:{self.PLC_ID}:analogs", json.dumps(self.analog_inputs))
            pipe.set(f"plc:{self.PLC_ID}:counters", json.dumps(self.counters))
            pipe.set(f"plc:{self.PLC_ID}:full_state", json.dumps(state))
            pipe.execute()
        except Exception as exc:
            log.debug("redis publish failed: %s", exc)

    def _publish_event(self, event: dict):
        if not self._redis:
            return
        try:
            log.info("Publishing event: %s", event)
            self._redis.publish("ot.protocol.write", json.dumps(event))
            self._redis.lpush(
                f"plc:{self.PLC_ID}:write_log", json.dumps(event)
            )
            self._redis.ltrim(f"plc:{self.PLC_ID}:write_log", 0, 999)
        except Exception:
            pass

    # ------------------- application payloads -------------------------- #
    def _build_class0_payload(self) -> bytes:
        """Build a Class 0 response payload containing BI, AI, and counters."""
        out = bytearray()

        # Object 1 var 2 (binary input with flags), qualifier 0x01 (start+stop, 1-byte)
        out += bytes([0x01, 0x02, 0x01, 0x00, len(self.binary_inputs) - 1])
        for v in self.binary_inputs:
            # flags: bit0 online, bit7 state
            flags = 0x01 | (0x80 if v else 0x00)
            out.append(flags)

        # Object 30 var 2 (16-bit analog input with flags), qualifier 0x01
        out += bytes([0x1E, 0x02, 0x01, 0x00, len(self.analog_inputs) - 1])
        for v in self.analog_inputs:
            out.append(0x01)  # online flag
            out += struct.pack("<h", max(-32768, min(32767, int(v))))

        # Object 20 var 1 (32-bit counter with flags), qualifier 0x01
        out += bytes([0x14, 0x01, 0x01, 0x00, len(self.counters) - 1])
        for v in self.counters:
            out.append(0x01)
            out += struct.pack("<I", int(v) & 0xFFFFFFFF)

        return bytes(out)

    def _build_flag_payload(self) -> bytes:
        """Build a payload containing the flag as an octet string object."""
        flag = b"SYSRUPT{dnp3_crc_m4st3r}"
        out = bytearray()
        # Object group 110 var 1 (octet string), qualifier 0x01, start=0 stop=0
        out += bytes([0x6E, 0x01, 0x01, 0x00, 0x00])
        out.append(len(flag))
        out += flag
        return bytes(out)

    def _build_app_response(self, req_seq: int, fc_response_to: int,
                            crc_valid: bool = False) -> bytes:
        """Build a complete application-layer message: transport + app + objects."""
        self._app_seq = (self._app_seq + 1) & 0x0F

        # Transport segment: FIR=1 FIN=1 seq=app_seq
        transport = 0xC0 | self._app_seq

        # Application control: FIR=1 FIN=1 CON=0 UNS=0 SEQ=req_seq (echo master's seq)
        app_ctrl = 0xC0 | (req_seq & 0x0F)

        fc_response = 0x81  # response
        iin1 = 0x00
        iin2 = 0x00

        if fc_response_to == 0x01:  # READ - return class 0 data
            payload = self._build_class0_payload()
        elif fc_response_to in (0x03, 0x05) and crc_valid:
            # CRC challenge solved - return the flag!
            payload = self._build_flag_payload()
        elif fc_response_to in (0x05, 0x06, 0x03):
            payload = b""
        else:
            payload = b""

        app_msg = bytes([app_ctrl, fc_response, iin1, iin2]) + payload
        return bytes([transport]) + app_msg

    def _build_link_response(self, user_data: bytes) -> bytes:
        """Wrap user_data in a DATA_UNCONFIRMED PRM=0 (outstation->master) frame."""
        # Control byte for an unconfirmed user data frame from outstation:
        # DIR=0 PRM=0 FCB=0 FCV=0 function=0 (RESET_LINK_STATES reply / user data)
        # Use 0x44 = DIR=0, PRM=1 would be master. Outstation responses use
        # PRM=0 with function "unconfirmed user data" = 0x01 at the link layer,
        # which encodes as control = 0x00 | 0x01 = 0x01 (DIR=0, PRM=0, FC=1).
        # Wireshark will still decode this as DNP3 given correct start bytes + CRC.
        ctrl = 0x44  # DIR=0 PRM=1 unconfirmed user data (common for responses in simple stacks)
        return build_link_frame(ctrl, self.MASTER_ADDR, self.OUTSTATION_ADDR, user_data)

    # ----------------------- tcp handler ------------------------------- #
    async def _handle_client(self, reader, writer):
        peer = writer.get_extra_info("peername")
        self._connected_clients += 1
        log.info("client connected: %s", peer)
        try:
            while True:
                header = await reader.readexactly(10)
                if header[0:2] != b"\x05\x64":
                    log.warning("bad start bytes from %s: %r", peer, header[:2])
                    return

                length = header[2]
                # length counts ctrl+dest+src+user_data (5 header bytes + payload)
                user_len = max(length - 5, 0)
                # How many 16-byte data chunks?
                n_chunks = (user_len + 15) // 16
                body_len = user_len + n_chunks * 2
                body = await reader.readexactly(body_len) if body_len > 0 else b""

                user_data = strip_link_data_crcs(body, user_len)

                if len(user_data) < 3:
                    # Link-layer only (RESET_LINK_STATES, TEST_LINK, etc).
                    # Send a short ACK frame with no user data.
                    ack = build_link_frame(0x00, self.MASTER_ADDR, self.OUTSTATION_ADDR, b"")
                    writer.write(ack)
                    await writer.drain()
                    continue

                # user_data = transport(1) + app_ctrl(1) + fc(1) + [objects...]
                app_ctrl = user_data[1]
                fc = user_data[2]
                req_seq = app_ctrl & 0x0F

                log.info("rx app fc=0x%02x seq=%d", fc, req_seq)

                if fc in (0x01, 0x02, 0x03, 0x04, 0x05):  # Any valid request
                    crc_valid = False
                    # Check for CRC challenge: Direct Operate with AO value
                    if fc in (0x03, 0x05):  # Direct Operate or Select
                        # Try to extract written value from app payload
                        try:
                            ao_data = user_data[3:]  # skip transport+ctrl+fc
                            # Look for analog output object (group 41) or any 16-bit value
                            for idx in range(len(ao_data) - 1):
                                val16 = ao_data[idx] | (ao_data[idx + 1] << 8)
                                if val16 == self._expected_crc:
                                    crc_valid = True
                                    log.info("CRC challenge SOLVED! Value 0x%04X matches", val16)
                                    break
                        except Exception:
                            pass
                    self._publish_event({
                        "plc_id": self.PLC_ID,
                        "protocol": "dnp3",
                        "operation": "direct_operate" if fc in (0x03, 0x05) else "read",
                        "crc_valid": crc_valid,
                        "raw": user_data.hex(),
                    })

                app_payload = self._build_app_response(req_seq, fc, crc_valid)
                frame = self._build_link_response(app_payload)
                writer.write(frame)
                await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionResetError):
            pass
        except Exception as exc:
            log.exception("handler error: %s", exc)
        finally:
            self._connected_clients -= 1
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    # ----------------------- scan / redis loops ------------------------ #
    async def _scan_loop(self):
        while self.running:
            # Small fluctuations on the first four differential pressures.
            for i in range(4):
                self.analog_inputs[i] = max(
                    10, min(600, self.analog_inputs[i] + random.randint(-2, 2))
                )
            # Turbidity drifts slightly
            self.analog_inputs[4] = max(0, min(300, self.analog_inputs[4] + random.randint(-1, 1)))
            self._scan_count += 1
            if self._scan_count % 5 == 0:
                self._publish_state()
            await asyncio.sleep(1)

    async def _redis_subscribe_loop(self):
        if not self._redis:
            return
        try:
            pubsub = self._redis.pubsub()
            pubsub.subscribe(f"physics:plc:{self.PLC_ID}:inputs")
        except Exception:
            return
        while self.running:
            try:
                msg = pubsub.get_message(timeout=1.0)
                if msg and msg.get("type") == "message":
                    try:
                        data = json.loads(msg["data"])
                        for k, v in data.items():
                            idx = int(k)
                            if 0 <= idx < len(self.analog_inputs):
                                self.analog_inputs[idx] = int(v)
                    except Exception:
                        pass
            except Exception:
                pass
            await asyncio.sleep(0.1)

    # ----------------------- entrypoint -------------------------------- #
    async def start(self):
        self.running = True
        self._publish_state()
        asyncio.create_task(self._scan_loop())
        asyncio.create_task(self._redis_subscribe_loop())
        server = await asyncio.start_server(self._handle_client, self.bind_ip, self.bind_port)
        sockets = ", ".join(str(s.getsockname()) for s in server.sockets)
        log.info("DNP3 outstation listening on %s", sockets)
        print(f"[PLC-3] DNP3 outstation listening on {sockets}", flush=True)
        async with server:
            await server.serve_forever()


def main():
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    )
    parser = argparse.ArgumentParser()
    parser.add_argument("--bind", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=20000)
    args = parser.parse_args()

    plc = FiltrationDNP3(bind_ip=args.bind, bind_port=args.port)
    try:
        asyncio.run(plc.start())
    except KeyboardInterrupt:
        plc.running = False
        print("[PLC-3] stopped")


if __name__ == "__main__":
    main()
