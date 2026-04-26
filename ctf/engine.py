"""CTF Auto-Detection Engine.

Watches Redis events from all OT Range services and automatically awards
challenges when students complete them.  No manual flag submission needed.
"""

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

import redis

log = logging.getLogger("ctf.engine")

# ---------------------------------------------------------------------------
# Challenge definition
# ---------------------------------------------------------------------------

@dataclass
class Challenge:
    """Single CTF challenge."""
    id: int
    name: str
    points: int
    description: str
    hints: List[str] = field(default_factory=list)

CHALLENGES: List[Challenge] = [
    Challenge(1, "perimeter_breach", 100, "Breach the corporate perimeter and gain initial access.",
              ["The corporate portal uses common default credentials.",
               "Try admin/admin123 on the login page.",
               "Check the admin panel after logging in."]),
    Challenge(2, "intelligence_gathering", 200, "Gather intelligence about the OT infrastructure through the OPC-UA gateway.",
              ["Browse the OPC-UA node tree for hidden data.",
               "Look under Maintenance > ServiceHistory.",
               "Read the Notes field in the service entries."]),
    Challenge(3, "pivot_to_ot", 300, "Pivot from the DMZ into the OT network.",
              ["The SCADA HMI is on the OT network.",
               "Try operator/scada_op! on the HMI login.",
               "Access the SCADA dashboard after logging in."]),
    Challenge(4, "building_recon_bacnet", 350, "Discover and enumerate the Building Management System via BACnet.",
              ["The BMS is on the corporate network at 10.0.1.20.",
               "Use a BACnet tool to read analog values.",
               "Read analog-value object 99 (AV:99)."]),
    Challenge(5, "deep_protocol_dnp3", 400, "Interact with the filtration PLC using DNP3 protocol.",
              ["The DNP3 outstation is on the process network.",
               "Use direct_operate or select/operate commands.",
               "Try writing to the filtration PLC via DNP3."]),
    Challenge(6, "deep_protocol_enip", 450, "Communicate with the distribution PLC using EtherNet/IP (CIP).",
              ["The EtherNet/IP server is on the process network.",
               "Use CIP explicit messaging with class_id 100.",
               "Write to tags using pylogix or cpppo client."]),
    Challenge(7, "deep_protocol_iec104", 500, "Access the power grid controller via IEC 60870-5-104.",
              ["The IEC 104 server is on the process network.",
               "Send a command to IOA 400.",
               "Use a 104 master to operate the breaker."]),
    Challenge(8, "process_manipulation_modbus", 600, "Manipulate the chemical dosing process by writing to Modbus registers.",
              ["You need to write to TWO registers on the chemical PLC.",
               "Register 9 controls manual mode, register 10 controls speed.",
               "Set register 9 to 0 (manual) AND register 10 above 50."]),
    Challenge(9, "safety_system_assault", 800, "Bypass the Safety Instrumented System via S7comm through the engineering workstation.",
              ["Connect to the SIS via the engineering workstation's safety bridge.",
               "Enable maintenance mode or modify setpoints.",
               "Write to DB2 offset 0 with a value above 800."]),
    Challenge(10, "full_compromise_stuxnet", 1000, "Achieve full plant compromise -- overdose chlorine while keeping the safety system disabled.",
              ["Disable the SIS first, then manipulate the chemical PLC.",
               "The physics engine must detect dangerous conditions.",
               "Wait for the physics:victory key to appear."]),
]

TOTAL_POINTS = sum(c.points for c in CHALLENGES)  # 4700

# Hint timing: 15/30/45 minutes
HINT_DELAYS_MIN = [15, 30, 45]

# Pub/sub channels
PUBSUB_CHANNELS = [
    "modbus.write",
    "ot.protocol.write",
    "sis.write",
    "sis.maintenance",
    "opcua.access",
    "bms.access",
]

# Polled keys
POLLED_KEYS = ["corp:admin_login", "scada:hmi_login", "physics:victory"]


# ---------------------------------------------------------------------------
# CTF Engine
# ---------------------------------------------------------------------------

class CTFEngine:
    """Auto-detection CTF engine."""

    def __init__(self, redis_host: str = "127.0.0.1", redis_port: int = 6379):
        self._r = redis.Redis(
            host=redis_host, port=redis_port, decode_responses=True
        )
        self._running = False
        self._threads: List[threading.Thread] = []
        self._lock = threading.Lock()

        # Challenge lookup
        self._challenges: Dict[int, Challenge] = {c.id: c for c in CHALLENGES}

        # State
        self._score = 0
        self._flags_captured: List[str] = []
        self._start_time: Optional[float] = None
        self._last_flag_time: Optional[float] = None

        # CH-08 compound condition tracking
        self.ch8_manual_mode = False
        self.ch8_speed_set = False

        # Load persisted state
        self._load_state()

    # ------------------------------------------------------------------ #
    # State persistence
    # ------------------------------------------------------------------ #

    def _load_state(self):
        """Restore state from Redis (survive restart)."""
        try:
            score = self._r.get("ctf:score")
            if score is not None:
                self._score = int(score)

            raw = self._r.get("ctf:flags_captured")
            if raw:
                self._flags_captured = json.loads(raw)

            st = self._r.get("ctf:start_time")
            if st and self._flags_captured:
                self._start_time = float(st)

            lt = self._r.get("ctf:last_flag_time")
            if lt:
                self._last_flag_time = float(lt)
        except Exception as exc:
            log.warning("Failed to load state from Redis: %s", exc)

    def _save_state(self):
        """Persist current state to Redis."""
        try:
            pipe = self._r.pipeline()
            pipe.set("ctf:score", str(self._score))
            pipe.set("ctf:flags_captured", json.dumps(self._flags_captured))
            if self._start_time and self._flags_captured:
                pipe.set("ctf:start_time", str(self._start_time))
            if self._last_flag_time:
                pipe.set("ctf:last_flag_time", str(self._last_flag_time))
            pipe.set("ctf:active", "1")
            pipe.set("ctf:total_challenges", str(len(CHALLENGES)))
            pipe.set("ctf:total_points", str(TOTAL_POINTS))
            pipe.execute()
        except Exception as exc:
            log.warning("Failed to save state: %s", exc)

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def start(self):
        """Start the engine daemon threads."""
        if self._running:
            return
        self._running = True

        if not self._start_time:
            self._start_time = time.time()

        self._save_state()

        t1 = threading.Thread(target=self._pubsub_listener, name="ctf-pubsub", daemon=True)
        t2 = threading.Thread(target=self._polling_loop, name="ctf-poll", daemon=True)
        t3 = threading.Thread(target=self._hint_timer, name="ctf-hints", daemon=True)
        self._threads = [t1, t2, t3]
        for t in self._threads:
            t.start()
        log.info("CTF engine started (%d challenges, %d pts total)", len(CHALLENGES), TOTAL_POINTS)

    def stop(self):
        """Stop the engine."""
        self._running = False
        for t in self._threads:
            t.join(timeout=2)
        self._threads.clear()
        log.info("CTF engine stopped")

    def reset(self):
        """Clear ALL CTF state from Redis."""
        try:
            keys = self._r.keys("ctf:*")
            if keys:
                self._r.delete(*keys)
            self._r.delete("physics:victory")
        except Exception as exc:
            log.warning("Reset failed: %s", exc)

        self._score = 0
        self._flags_captured = []
        self._start_time = None
        self._last_flag_time = None
        self.ch8_manual_mode = False
        self.ch8_speed_set = False
        log.info("CTF state reset")

    def award(self, challenge_id: int):
        """Award a challenge by ID."""
        with self._lock:
            cid = str(challenge_id)
            if cid in self._flags_captured:
                return  # already awarded

            ch = self._challenges.get(challenge_id)
            if not ch:
                log.warning("Unknown challenge ID: %d", challenge_id)
                return

            # Set start time on first capture
            if not self._start_time:
                self._start_time = time.time()

            now = time.time()
            self._flags_captured.append(cid)
            self._score += ch.points
            self._last_flag_time = now

            # Per-challenge detail
            detail = {
                "id": challenge_id,
                "name": ch.name,
                "points": ch.points,
                "captured_at": datetime.now(timezone.utc).isoformat(),
                "elapsed_s": round(now - self._start_time, 1) if self._start_time else 0,
            }
            try:
                self._r.set(f"ctf:challenge:{challenge_id}", json.dumps(detail))
            except Exception:
                pass

            self._save_state()

            # Publish event for display
            try:
                self._r.publish("ctf:flag_captured", json.dumps(detail))
            except Exception:
                pass

            log.info(
                "CH-%02d CAPTURED: %s (+%d pts, total %d/%d)",
                challenge_id, ch.name, ch.points, self._score, TOTAL_POINTS,
            )

    @property
    def score(self) -> int:
        return self._score

    @property
    def flags_captured(self) -> List[str]:
        return list(self._flags_captured)

    @property
    def start_time(self) -> Optional[float]:
        return self._start_time

    # ------------------------------------------------------------------ #
    # Thread 1: Pub/sub listener
    # ------------------------------------------------------------------ #

    def _pubsub_listener(self):
        """Subscribe to Redis channels and dispatch events."""
        ps = self._r.pubsub()
        ps.subscribe(*PUBSUB_CHANNELS)
        log.info("Subscribed to channels: %s", PUBSUB_CHANNELS)

        while self._running:
            try:
                msg = ps.get_message(timeout=0.5)
                if msg and msg["type"] == "message":
                    channel = msg["channel"]
                    try:
                        data = json.loads(msg["data"])
                    except (json.JSONDecodeError, TypeError):
                        data = {}
                    self._process_event(channel, data)
            except Exception as exc:
                log.debug("pubsub error: %s", exc)
                time.sleep(1)

        try:
            ps.unsubscribe()
            ps.close()
        except Exception:
            pass

    def _process_event(self, channel: str, data: dict):
        """Route a pub/sub event to the appropriate challenge detector."""

        # CH-02: OPC-UA deep browse
        if channel == "opcua.access":
            node_path = data.get("node_path", "")
            if "ServiceHistory" in node_path:
                self.award(2)

        # CH-04: BACnet BMS read of AV:99
        elif channel == "bms.access":
            obj = data.get("object", "")
            if obj == "AV:99":
                self.award(4)

        # CH-05/06/07: OT protocol writes
        elif channel == "ot.protocol.write":
            protocol = data.get("protocol", "").lower()

            # CH-05: DNP3 - student must solve CRC challenge
            if protocol == "dnp3":
                if data.get("crc_valid") is True:
                    self.award(5)

            # CH-06: EtherNet/IP - silent overpressure (alarm disabled + pressure > threshold)
            elif protocol == "enip":
                event = data.get("event", "")
                if event == "silent_overpressure":
                    self.award(6)

            # CH-07: IEC 104
            elif protocol in ("iec104", "iec-60870-5-104"):
                ioa = data.get("ioa")
                if ioa is not None:
                    try:
                        if int(ioa) == 400:
                            self.award(7)
                    except (ValueError, TypeError):
                        pass

        # CH-08: Modbus write on chemical PLC (compound condition)
        elif channel == "modbus.write":
            plc_id = data.get("plc_id", "")
            if plc_id == "chemical":
                addr = data.get("address")
                values = data.get("values", [])
                if addr is not None and values:
                    try:
                        addr = int(addr)
                        val = int(values[0]) if isinstance(values, list) else int(values)
                    except (ValueError, TypeError, IndexError):
                        return

                    if addr == 9 and val == 0:
                        self.ch8_manual_mode = True
                    elif addr == 10 and val > 50:
                        self.ch8_speed_set = True

                    if self.ch8_manual_mode and self.ch8_speed_set:
                        self.award(8)

        # CH-09: SIS maintenance or setpoint write
        elif channel == "sis.maintenance":
            enabled = data.get("enabled")
            if enabled is True or str(enabled).lower() == "true":
                self.award(9)

        elif channel == "sis.write":
            db = data.get("db")
            offset = data.get("offset")
            value = data.get("value")
            if db is not None and offset is not None and value is not None:
                try:
                    if int(db) == 2 and int(offset) == 0 and int(value) > 800:
                        self.award(9)
                except (ValueError, TypeError):
                    pass

    # ------------------------------------------------------------------ #
    # Thread 2: Polling loop
    # ------------------------------------------------------------------ #

    def _polling_loop(self):
        """Poll Redis keys every 1 second."""
        while self._running:
            try:
                # CH-01: Corporate admin login
                if self._r.exists("corp:admin_login"):
                    self.award(1)

                # CH-03: SCADA HMI login
                if self._r.exists("scada:hmi_login"):
                    self.award(3)

                # CH-10: Physics victory
                if self._r.exists("physics:victory"):
                    self.award(10)

            except Exception as exc:
                log.debug("polling error: %s", exc)
            time.sleep(1)

    # ------------------------------------------------------------------ #
    # Thread 3: Hint timer
    # ------------------------------------------------------------------ #

    def _hint_timer(self):
        """Calculate hint availability based on elapsed time."""
        while self._running:
            if self._start_time and self._flags_captured:
                elapsed_min = (time.time() - self._start_time) / 60.0
                hint_level = 0
                for delay in HINT_DELAYS_MIN:
                    if elapsed_min >= delay:
                        hint_level += 1
                    else:
                        break

                hint_state = {
                    "elapsed_min": round(elapsed_min, 1),
                    "hint_level": hint_level,
                    "max_level": len(HINT_DELAYS_MIN),
                }
                try:
                    self._r.set("ctf:hint_state", json.dumps(hint_state))

                    # Notify display of new hint level per challenge
                    for ch in CHALLENGES:
                        cid = str(ch.id)
                        if cid in self._flags_captured:
                            continue
                        prev_key = f"ctf:hint_prev_level:{ch.id}"
                        prev = self._r.get(prev_key)
                        prev_level = int(prev) if prev else 0
                        avail = min(hint_level, len(ch.hints))
                        if avail > prev_level:
                            self._r.set(prev_key, str(avail))
                except Exception:
                    pass

            time.sleep(5)


# ---------------------------------------------------------------------------
# Standalone entry point
# ---------------------------------------------------------------------------

def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    engine = CTFEngine()
    engine.start()
    log.info("CTF auto-detection engine running. Press Ctrl+C to stop.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        engine.stop()


if __name__ == "__main__":
    main()
