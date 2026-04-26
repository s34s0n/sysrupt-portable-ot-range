#!/usr/bin/env python3
"""
Safety Instrumented System (SIS) - S7comm Server
Listens on port 102 (ISO-on-TCP / S7comm) using python-snap7.
Implements safety trip logic with latching, maintenance bypass, and hidden flag.
"""

import json
import logging
import os
import signal
import struct
import sys
import threading
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(os.path.dirname(_HERE))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import snap7
from snap7.server import Server as S7Server
from snap7.type import SrvArea

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
log = logging.getLogger("safety-sis")

# ---------------------------------------------------------------------------
# Redis helper (same pattern as other PLCs)
# ---------------------------------------------------------------------------
_redis = None


def _get_redis():
    global _redis
    if _redis is not None:
        try:
            _redis.ping()
            return _redis
        except Exception:
            _redis = None
    import redis as _redis_mod
    # Try common gateway IPs used by bridge networks
    for host in ("10.0.5.1", "10.0.4.1", "10.0.3.1", "10.0.2.1",
                 "10.0.1.1", "172.17.0.1", "127.0.0.1"):
        try:
            r = _redis_mod.Redis(host=host, port=6379, decode_responses=True,
                                 socket_connect_timeout=0.5)
            r.ping()
            log.info("Redis connected at %s:6379", host)
            _redis = r
            return r
        except Exception:
            continue
    log.warning("Redis not available - running without state sharing")
    return None


# ---------------------------------------------------------------------------
# Data-block layout
# ---------------------------------------------------------------------------
# DB1 - Safety status (64 bytes)
#   DBX0.0  sis_armed        BOOL
#   DBX0.1  sis_tripped      BOOL
#   DBX0.2  sis_healthy      BOOL
#   DBX0.3  trip_active      BOOL   (relay commanded)
#   DBX0.4  maintenance_mode BOOL
#   DBW2    trip_code        INT    (reason: 0=none,1=cl_hi,2=cl_lo,3=ph_hi,4=ph_lo,5=level)
#   DBD4    chlorine_ppm     REAL   (x100 INT stored)
#   DBD8    ph               REAL   (x100 INT stored)
#   DBD12   level_pct        REAL   (x100 INT stored)
#   DBW16   scan_count       UINT
#   DBW18   uptime_s         UINT
#   DBW20   trip_count       UINT

# DB2 - Setpoints (32 bytes)
#   DBW0    cl_trip_high     INT (x100 => 500 = 5.00 ppm)
#   DBW2    cl_trip_low      INT (x100 => 10  = 0.10 ppm)
#   DBW4    ph_trip_high     INT (x100 => 900 = 9.00)
#   DBW6    ph_trip_low      INT (x100 => 600 = 6.00)
#   DBW8    level_trip       INT (percent)
#   DBW10   trip_delay_ms    INT
#   DBW12   auto_reset       INT (0=off, 1=on)
#   DBW14   maintenance_pw   INT (password for maintenance bypass)

# DB3 - Trip history (128 bytes) - 8 entries of 16 bytes each
#   Each entry: timestamp(4), code(2), cl(2), ph(2), lvl(2), reserved(4)

# DB99 - Hidden flag (32 bytes)
#   10 INT words encoding the flag string

DB1_SIZE = 64
DB2_SIZE = 32
DB3_SIZE = 128
DB99_SIZE = 32
MK_SIZE = 16
QA_SIZE = 4


def _encode_flag(flag_str):
    """Encode flag string into 10 big-endian INT words (20 bytes)."""
    padded = flag_str.ljust(20, '\x00')[:20]
    pairs = [(padded[i], padded[i + 1]) for i in range(0, 20, 2)]
    return struct.pack('>10H', *[ord(c1) << 8 | ord(c2) for c1, c2 in pairs])


class SafetySIS:
    """S7comm Safety Instrumented System."""

    FLAG = "SYSRUPT{s7_s4f3ty_byp4ss}"

    def __init__(self, bind_ip="0.0.0.0", bind_port=102):
        self.bind_ip = bind_ip
        self.bind_port = bind_port
        self._server = S7Server()

        # Allocate data blocks
        self.db1 = bytearray(DB1_SIZE)
        self.db2 = bytearray(DB2_SIZE)
        self.db3 = bytearray(DB3_SIZE)
        self.db99 = bytearray(DB99_SIZE)
        self.mk = bytearray(MK_SIZE)
        self.qa = bytearray(QA_SIZE)

        # Trip timing state
        self._trip_pending_since = {}  # code -> timestamp
        self._trip_history_idx = 0
        self._scan_count = 0
        self._start_time = time.time()
        self._running = False
        self._scan_thread = None

        self._init_data_blocks()
        # CTF: track previous DB2 state for write detection
        self._prev_db2 = bytearray(self.db2)

    def _init_data_blocks(self):
        """Set initial values for all data blocks."""
        # DB1: sis_armed=True, sis_tripped=False, sis_healthy=True
        self.db1[0] = 0b00000101  # bit0=armed, bit2=healthy
        # trip_code = 0
        struct.pack_into('>H', self.db1, 2, 0)

        # DB2: setpoints
        struct.pack_into('>H', self.db2, 0, 500)    # cl_trip_high (5.00 ppm)
        struct.pack_into('>H', self.db2, 2, 10)     # cl_trip_low  (0.10 ppm)
        struct.pack_into('>H', self.db2, 4, 900)    # ph_trip_high (9.00)
        struct.pack_into('>H', self.db2, 6, 600)    # ph_trip_low  (6.00)
        struct.pack_into('>H', self.db2, 8, 95)     # level_trip   (95%)
        struct.pack_into('>H', self.db2, 10, 2000)  # trip_delay_ms
        struct.pack_into('>H', self.db2, 12, 0)     # auto_reset
        struct.pack_into('>H', self.db2, 14, 7777)  # maintenance_password

        # DB99: hidden flag
        flag_bytes = _encode_flag(self.FLAG)
        self.db99[:len(flag_bytes)] = flag_bytes

    @property
    def running(self):
        return self._running

    def start(self):
        """Register areas and start the S7 server + scan cycle."""
        self._server.register_area(SrvArea.DB, 1, self.db1)
        self._server.register_area(SrvArea.DB, 2, self.db2)
        self._server.register_area(SrvArea.DB, 3, self.db3)
        self._server.register_area(SrvArea.DB, 99, self.db99)
        self._server.register_area(SrvArea.MK, 0, self.mk)
        self._server.register_area(SrvArea.PA, 0, self.qa)

        self._server.start_to(self.bind_ip, self.bind_port)
        self._running = True
        self._start_time = time.time()
        log.info("S7comm SIS server listening on %s:%d", self.bind_ip, self.bind_port)

        # Start safety scan cycle
        self._scan_thread = threading.Thread(target=self._scan_loop, daemon=True)
        self._scan_thread.start()

    def stop(self):
        """Stop the server and scan thread."""
        self._running = False
        try:
            self._server.stop()
        except Exception:
            pass
        log.info("SIS server stopped")

    # -- DB access helpers ---------------------------------------------------
    def _get_bit(self, db, byte_idx, bit_idx):
        return bool(db[byte_idx] & (1 << bit_idx))

    def _set_bit(self, db, byte_idx, bit_idx, value):
        if value:
            db[byte_idx] |= (1 << bit_idx)
        else:
            db[byte_idx] &= ~(1 << bit_idx)

    def _get_int(self, db, offset):
        return struct.unpack_from('>H', db, offset)[0]

    def _set_int(self, db, offset, value):
        struct.pack_into('>H', db, offset, value & 0xFFFF)

    # -- Properties ----------------------------------------------------------
    @property
    def sis_armed(self):
        return self._get_bit(self.db1, 0, 0)

    @property
    def sis_tripped(self):
        return self._get_bit(self.db1, 0, 1)

    @property
    def sis_healthy(self):
        return self._get_bit(self.db1, 0, 2)

    @property
    def maintenance_mode(self):
        return self._get_bit(self.db1, 0, 4)

    @property
    def status_str(self):
        if self.maintenance_mode:
            return "maintenance"
        if self.sis_tripped:
            return "tripped"
        return "armed"

    # -- Scan cycle ----------------------------------------------------------
    def _read_sensors(self):
        """Read sensor data from Redis or use simulated values."""
        r = _get_redis()
        if r:
            try:
                raw = r.get("physics:sis:sensors")
                if raw:
                    data = json.loads(raw)
                    return (
                        float(data.get("chlorine_ppm", 1.5)),
                        float(data.get("ph", 7.2)),
                        float(data.get("level_pct", 60.0)),
                    )
            except Exception:
                pass
            # Fallback: try hw sensors
            try:
                raw_temp = r.get("hw:temp:temp_process")
                # Use temp as proxy for chlorine if available
            except Exception:
                pass

        # Simulated defaults with slight noise
        import random
        cl = 1.5 + random.uniform(-0.1, 0.1)
        ph = 7.2 + random.uniform(-0.05, 0.05)
        lvl = 60.0 + random.uniform(-2.0, 2.0)
        return cl, ph, lvl

    def _check_trip(self, code, condition, delay_ms):
        """Check if a trip condition has persisted long enough."""
        now = time.time()
        if condition:
            if code not in self._trip_pending_since:
                self._trip_pending_since[code] = now
            elif (now - self._trip_pending_since[code]) * 1000 >= delay_ms:
                return True
        else:
            self._trip_pending_since.pop(code, None)
        return False

    def _execute_trip(self, code, cl, ph, lvl):
        """Execute a safety trip."""
        self._set_bit(self.db1, 0, 1, True)   # sis_tripped
        self._set_bit(self.db1, 0, 3, True)   # trip_active
        self._set_int(self.db1, 2, code)       # trip_code
        self.qa[0] |= 0x01                     # Q0.0 trip relay

        # Update trip count
        count = self._get_int(self.db1, 20)
        self._set_int(self.db1, 20, count + 1)

        # Log to DB3 history
        idx = self._trip_history_idx % 8
        offset = idx * 16
        ts = int(time.time()) & 0xFFFFFFFF
        struct.pack_into('>I', self.db3, offset, ts)
        struct.pack_into('>H', self.db3, offset + 4, code)
        struct.pack_into('>H', self.db3, offset + 6, int(cl * 100))
        struct.pack_into('>H', self.db3, offset + 8, int(ph * 100))
        struct.pack_into('>H', self.db3, offset + 10, int(lvl * 100))
        self._trip_history_idx += 1

        log.warning("SIS TRIP! Code=%d cl=%.2f ph=%.2f lvl=%.1f%%", code, cl, ph, lvl)

        # Publish to Redis
        r = _get_redis()
        if r:
            try:
                r.publish("sis.trip", json.dumps({
                    "code": code,
                    "chlorine_ppm": round(cl, 2),
                    "ph": round(ph, 2),
                    "level_pct": round(lvl, 1),
                    "timestamp": time.time(),
                }))
            except Exception:
                pass

    def _scan_cycle(self):
        """One scan cycle of safety logic."""
        self._scan_count += 1

        cl, ph, lvl = self._read_sensors()

        # Update sensor readings in DB1
        self._set_int(self.db1, 4, int(cl * 100))
        self._set_int(self.db1, 8, int(ph * 100))
        self._set_int(self.db1, 12, int(lvl * 100))
        self._set_int(self.db1, 16, self._scan_count & 0xFFFF)
        self._set_int(self.db1, 18, int(time.time() - self._start_time) & 0xFFFF)

        # CTF: detect DB2 writes by comparing with previous state
        if self.db2 != self._prev_db2:
            r_db2 = _get_redis()
            if r_db2:
                for offset in range(0, min(len(self.db2), len(self._prev_db2)), 2):
                    old_val = struct.unpack_from('>H', self._prev_db2, offset)[0]
                    new_val = struct.unpack_from('>H', self.db2, offset)[0]
                    if old_val != new_val:
                        try:
                            r_db2.publish("sis.write", json.dumps({
                                "db": 2,
                                "offset": offset,
                                "value": new_val,
                                "old_value": old_val,
                                "timestamp": time.time(),
                            }))
                        except Exception:
                            pass
            self._prev_db2 = bytearray(self.db2)

        # Read setpoints from DB2 (may have been modified by S7 client)
        cl_hi = self._get_int(self.db2, 0)
        cl_lo = self._get_int(self.db2, 2)
        ph_hi = self._get_int(self.db2, 4)
        ph_lo = self._get_int(self.db2, 6)
        lvl_trip = self._get_int(self.db2, 8)
        delay_ms = self._get_int(self.db2, 10)
        auto_reset = self._get_int(self.db2, 12)
        maint_pw = self._get_int(self.db2, 14)

        # Maintenance mode check: password == 7777 AND maintenance bit set
        if maint_pw == 7777 and self._get_bit(self.db1, 0, 4):
            # Maintenance mode active - bypass trips
            # CTF: publish sis.maintenance event
            r = _get_redis()
            if r:
                try:
                    r.publish("sis.maintenance", json.dumps({
                        "enabled": True,
                        "timestamp": time.time(),
                    }))
                except Exception:
                    pass
        elif not self.sis_tripped:
            # Check trip conditions
            if self._check_trip(1, cl * 100 >= cl_hi, delay_ms):
                self._execute_trip(1, cl, ph, lvl)
            elif self._check_trip(2, cl * 100 <= cl_lo, delay_ms):
                self._execute_trip(2, cl, ph, lvl)
            elif self._check_trip(3, ph * 100 >= ph_hi, delay_ms):
                self._execute_trip(3, cl, ph, lvl)
            elif self._check_trip(4, ph * 100 <= ph_lo, delay_ms):
                self._execute_trip(4, cl, ph, lvl)
            elif self._check_trip(5, lvl >= lvl_trip, delay_ms):
                self._execute_trip(5, cl, ph, lvl)

        # Auto reset (if enabled and trip condition cleared)
        if self.sis_tripped and auto_reset == 1:
            # Only reset if no active trip conditions
            if not (cl * 100 >= cl_hi or cl * 100 <= cl_lo or
                    ph * 100 >= ph_hi or ph * 100 <= ph_lo or lvl >= lvl_trip):
                self.reset_trip()

        # Publish state to Redis
        self._publish_state(cl, ph, lvl)

    def reset_trip(self):
        """Manual trip reset."""
        self._set_bit(self.db1, 0, 1, False)  # clear tripped
        self._set_bit(self.db1, 0, 3, False)  # clear trip_active
        self._set_int(self.db1, 2, 0)          # clear trip code
        self.qa[0] &= ~0x01                    # clear relay
        self._trip_pending_since.clear()
        log.info("SIS trip reset")

    def _publish_state(self, cl, ph, lvl):
        """Publish current state to Redis."""
        r = _get_redis()
        if not r:
            return
        try:
            r.set("sis:status", self.status_str)
            r.set("sis:sensors", json.dumps({
                "chlorine_ppm": round(cl, 2),
                "ph": round(ph, 2),
                "level_pct": round(lvl, 1),
            }))
            r.set("sis:setpoints", json.dumps({
                "cl_trip_high": self._get_int(self.db2, 0) / 100,
                "cl_trip_low": self._get_int(self.db2, 2) / 100,
                "ph_trip_high": self._get_int(self.db2, 4) / 100,
                "ph_trip_low": self._get_int(self.db2, 6) / 100,
                "level_trip": self._get_int(self.db2, 8),
                "trip_delay_ms": self._get_int(self.db2, 10),
                "auto_reset": self._get_int(self.db2, 12),
            }))
            r.set("sis:trip_count", str(self._get_int(self.db1, 20)))
        except Exception:
            pass

    def _scan_loop(self):
        """Background thread running safety scans at 100ms intervals."""
        log.info("Safety scan loop started (100ms cycle)")
        while self._running:
            try:
                self._scan_cycle()
            except Exception as e:
                log.error("Scan cycle error: %s", e)
            time.sleep(0.1)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    bind_ip = os.environ.get("BIND_IP", "0.0.0.0")
    bind_port = int(os.environ.get("BIND_PORT", "102"))

    sis = SafetySIS(bind_ip=bind_ip, bind_port=bind_port)

    def _shutdown(signum, frame):
        log.info("Shutting down (signal %d)...", signum)
        sis.stop()
        sys.exit(0)

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    sis.start()

    # Keep main thread alive
    try:
        while sis.running:
            time.sleep(1)
    except KeyboardInterrupt:
        sis.stop()


if __name__ == "__main__":
    main()
