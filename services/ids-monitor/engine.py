"""IDS Engine -- Intrusion Detection System for Sysrupt OT Range.

Subscribes to Redis pub/sub channels, applies 22+ detection rules,
and publishes alerts for the display and SCADA HMI.
"""

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

import redis

log = logging.getLogger("ids.engine")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ALLOWED_MODBUS_SOURCES = ["10.0.4.10", "10.0.3.10", "127.0.0.1"]

PUBSUB_CHANNELS = [
    "modbus.write",
    "ot.protocol.write",
    "sis.write",
    "sis.maintenance",
    "opcua.access",
    "bms.access",
]

PHYSICS_POLL_INTERVAL = 5  # seconds

ALERT_HISTORY_MAX = 100
ALERT_DISPLAY_MAX = 20
THREAT_WINDOW_SEC = 300  # 5 minutes


# ---------------------------------------------------------------------------
# Severity
# ---------------------------------------------------------------------------

class AlertSeverity:
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"

    _ORDER = {"LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}

    @classmethod
    def rank(cls, severity: str) -> int:
        return cls._ORDER.get(severity, 0)


# ---------------------------------------------------------------------------
# Rule definition
# ---------------------------------------------------------------------------

@dataclass
class IDSRule:
    rule_id: str
    name: str
    severity: str
    description: str
    cooldown: float  # seconds, 0 = always fire
    last_triggered: float = 0.0
    trigger_count: int = 0

    def can_trigger(self) -> bool:
        if self.cooldown == 0:
            return True
        return (time.time() - self.last_triggered) >= self.cooldown

    def mark_triggered(self):
        self.last_triggered = time.time()
        self.trigger_count += 1


# ---------------------------------------------------------------------------
# All 22+ rules
# ---------------------------------------------------------------------------

def _build_rules() -> Dict[str, IDSRule]:
    defs = [
        # Recon
        ("IDS-001", "Port Scan Detected", AlertSeverity.LOW,
         "Multiple connection attempts from same source in short window", 60),
        ("IDS-002", "OPC-UA Enumeration", AlertSeverity.LOW,
         "OPC-UA browse/enumeration activity detected", 120),
        ("IDS-003", "BACnet Discovery", AlertSeverity.LOW,
         "BACnet WhoIs discovery broadcast detected", 120),
        ("IDS-004", "Modbus Device Scan", AlertSeverity.LOW,
         "Modbus device scanning activity detected", 60),

        # Unauthorized Access
        ("IDS-010", "Unauthorized Modbus Source", AlertSeverity.MEDIUM,
         "Modbus write from unauthorized IP address", 30),
        ("IDS-011", "Unauthorized S7comm Access", AlertSeverity.HIGH,
         "S7comm write to safety PLC from unauthorized source", 10),
        ("IDS-012", "Unauthorized DNP3 Control", AlertSeverity.MEDIUM,
         "DNP3 control operation from unauthorized source", 30),
        ("IDS-013", "Unauthorized ENIP Write", AlertSeverity.MEDIUM,
         "EtherNet/IP CIP write from unauthorized source", 30),
        ("IDS-014", "Unauthorized IEC104 Command", AlertSeverity.HIGH,
         "IEC 60870-5-104 command from unauthorized source", 10),

        # Process Anomalies
        ("IDS-020", "PID Mode Change to Manual", AlertSeverity.HIGH,
         "Chemical PLC PID controller switched to manual mode", 0),
        ("IDS-021", "Setpoint Change Anomaly", AlertSeverity.MEDIUM,
         "Chemical PLC setpoint changed >50%% from expected value", 30),
        ("IDS-022", "Alarm Inhibit Activated", AlertSeverity.CRITICAL,
         "Process alarms have been suppressed", 0),
        ("IDS-023", "Alarm Threshold Raised", AlertSeverity.CRITICAL,
         "Alarm threshold raised to dangerous level", 0),
        ("IDS-024", "Manual Dosing Excessive", AlertSeverity.HIGH,
         "Manual dosing pump speed set above 80%%", 30),
        ("IDS-025-M", "Chlorine Level Elevated", AlertSeverity.MEDIUM,
         "Chlorine level above 2.0 ppm", 60),
        ("IDS-025-H", "Chlorine Level High", AlertSeverity.HIGH,
         "Chlorine level above 4.0 ppm", 60),
        ("IDS-025-C", "Chlorine Level Critical", AlertSeverity.CRITICAL,
         "Chlorine level above 6.0 ppm", 60),

        # Safety System
        ("IDS-030", "SIS Maintenance Mode Enabled", AlertSeverity.CRITICAL,
         "Safety Instrumented System placed in maintenance mode", 0),
        ("IDS-031", "SIS Trip Threshold Modified", AlertSeverity.CRITICAL,
         "SIS trip threshold has been changed", 0),
        ("IDS-032", "SIS Trip Delay Increased", AlertSeverity.HIGH,
         "SIS trip delay increased beyond safe limit", 0),

        # Program Manipulation
        ("IDS-040", "PLC Program Upload", AlertSeverity.CRITICAL,
         "PLC program uploaded -- possible logic modification", 0),
        ("IDS-041", "PLC Program Download", AlertSeverity.MEDIUM,
         "PLC program downloaded -- reconnaissance activity", 120),

        # Infrastructure
        ("IDS-050", "Power Breaker Open Command", AlertSeverity.CRITICAL,
         "IEC 104 command to open power breaker", 0),
        ("IDS-051", "OPC-UA Write from DMZ", AlertSeverity.HIGH,
         "OPC-UA write operation originating from DMZ network", 30),
    ]
    rules = {}
    for rule_id, name, severity, desc, cooldown in defs:
        rules[rule_id] = IDSRule(
            rule_id=rule_id, name=name, severity=severity,
            description=desc, cooldown=cooldown,
        )
    return rules


# ---------------------------------------------------------------------------
# IDS Engine
# ---------------------------------------------------------------------------

class IDSEngine:
    """Main IDS engine -- pub/sub listener + physics poller."""

    def __init__(self, redis_host: str = "127.0.0.1", redis_port: int = 6379):
        self._r = redis.Redis(
            host=redis_host, port=redis_port, decode_responses=True,
        )
        self._running = False
        self._threads: List[threading.Thread] = []
        self._lock = threading.Lock()

        self.rules: Dict[str, IDSRule] = _build_rules()
        self._alerts: List[dict] = []
        self._alert_count = 0

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def start(self):
        if self._running:
            return
        self._running = True

        try:
            self._r.set("ids:active", "true")
            self._r.set("ids:alert_count", "0")
            self._r.set("ids:threat_level", "NONE")
            self._r.set("ids:alerts", "[]")
        except Exception as exc:
            log.warning("Failed to init Redis state: %s", exc)

        t1 = threading.Thread(target=self._pubsub_listener, name="ids-pubsub", daemon=True)
        t2 = threading.Thread(target=self._physics_poller, name="ids-physics", daemon=True)
        self._threads = [t1, t2]
        for t in self._threads:
            t.start()
        log.info("IDS engine started (%d rules loaded)", len(self.rules))

    def stop(self):
        self._running = False
        for t in self._threads:
            t.join(timeout=2)
        self._threads.clear()
        try:
            self._r.set("ids:active", "false")
        except Exception:
            pass
        log.info("IDS engine stopped")

    def reset(self):
        with self._lock:
            self._alerts.clear()
            self._alert_count = 0
            for rule in self.rules.values():
                rule.last_triggered = 0.0
                rule.trigger_count = 0
        try:
            keys = self._r.keys("ids:*")
            if keys:
                self._r.delete(*keys)
        except Exception as exc:
            log.warning("Reset failed: %s", exc)
        log.info("IDS state reset")

    @property
    def alert_count(self) -> int:
        return self._alert_count

    @property
    def alerts(self) -> List[dict]:
        with self._lock:
            return list(self._alerts)

    @property
    def threat_level(self) -> str:
        return self._calculate_threat_level()

    # ------------------------------------------------------------------ #
    # Alert firing
    # ------------------------------------------------------------------ #

    def fire_rule(self, rule_id: str, source_ip: str = "", details: Optional[dict] = None):
        rule = self.rules.get(rule_id)
        if not rule:
            log.warning("Unknown rule: %s", rule_id)
            return

        if not rule.can_trigger():
            return

        rule.mark_triggered()

        alert = {
            "rule_id": rule.rule_id,
            "name": rule.name,
            "severity": rule.severity,
            "description": rule.description,
            "source_ip": source_ip,
            "details": details or {},
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
            "trigger_count": rule.trigger_count,
        }

        with self._lock:
            self._alerts.append(alert)
            self._alert_count += 1
            # Trim history
            if len(self._alerts) > ALERT_HISTORY_MAX:
                self._alerts = self._alerts[-ALERT_HISTORY_MAX:]

        self._publish_alert(alert)

    def _publish_alert(self, alert: dict):
        try:
            pipe = self._r.pipeline()
            pipe.set("ids:alert_count", str(self._alert_count))
            pipe.set("ids:latest_alert", json.dumps(alert))
            pipe.set("ids:threat_level", self._calculate_threat_level())

            # Store last 20 alerts for display
            with self._lock:
                display_alerts = self._alerts[-ALERT_DISPLAY_MAX:]
            pipe.set("ids:alerts", json.dumps(display_alerts))

            pipe.execute()

            # Publish for real-time subscribers
            self._r.publish("ids:alert", json.dumps(alert))
        except Exception as exc:
            log.warning("Failed to publish alert: %s", exc)

    # ------------------------------------------------------------------ #
    # Threat level calculation (last 5 minutes)
    # ------------------------------------------------------------------ #

    def _calculate_threat_level(self) -> str:
        now = time.time()
        cutoff = now - THREAT_WINDOW_SEC

        with self._lock:
            recent = [a for a in self._alerts if self._alert_timestamp(a) >= cutoff]

        if not recent:
            return "NONE"

        severities = [a["severity"] for a in recent]

        if AlertSeverity.CRITICAL in severities:
            return "CRITICAL"

        if AlertSeverity.HIGH in severities or severities.count(AlertSeverity.MEDIUM) >= 3:
            return "HIGH"

        if AlertSeverity.MEDIUM in severities or severities.count(AlertSeverity.LOW) >= 4:
            return "MEDIUM"

        if len(severities) <= 3:
            return "LOW"

        return "MEDIUM"

    @staticmethod
    def _alert_timestamp(alert: dict) -> float:
        ts = alert.get("timestamp", "")
        try:
            dt = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S")
            dt = dt.replace(tzinfo=timezone.utc)
            return dt.timestamp()
        except (ValueError, TypeError):
            return 0.0

    # ------------------------------------------------------------------ #
    # Pub/sub listener
    # ------------------------------------------------------------------ #

    def _pubsub_listener(self):
        ps = self._r.pubsub()
        ps.subscribe(*PUBSUB_CHANNELS)
        log.info("IDS subscribed to: %s", PUBSUB_CHANNELS)

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
        source_ip = data.get("source_ip", data.get("client_ip", ""))

        # ----- modbus.write -----
        if channel == "modbus.write":
            plc_id = data.get("plc_id", "")

            # IDS-004: Modbus device scan (non-chemical PLC or no plc_id)
            if data.get("scan"):
                self.fire_rule("IDS-004", source_ip, {"plc_id": plc_id})

            # IDS-010: Unauthorized source
            if source_ip and source_ip not in ALLOWED_MODBUS_SOURCES:
                self.fire_rule("IDS-010", source_ip, {"plc_id": plc_id})

            # Process anomaly rules (chemical PLC)
            if plc_id == "chemical":
                addr = data.get("address")
                values = data.get("values", [])
                if addr is not None and values:
                    try:
                        addr = int(addr)
                        val = int(values[0]) if isinstance(values, list) else int(values)
                    except (ValueError, TypeError, IndexError):
                        return

                    # IDS-020: PID mode change to manual
                    if addr == 9 and val == 0:
                        self.fire_rule("IDS-020", source_ip, {"address": addr, "value": val})

                    # IDS-021: Setpoint change >50% from expected (150)
                    if addr == 0 and abs(val - 150) > 75:
                        self.fire_rule("IDS-021", source_ip, {"address": addr, "value": val, "expected": 150})

                    # IDS-022: Alarm inhibit
                    if addr == 15 and val == 1:
                        self.fire_rule("IDS-022", source_ip, {"address": addr, "value": val})

                    # IDS-023: Alarm threshold raised >500
                    if addr == 1 and val > 500:
                        self.fire_rule("IDS-023", source_ip, {"address": addr, "value": val})

                    # IDS-024: Manual dosing >80%
                    if addr == 10 and val > 80:
                        self.fire_rule("IDS-024", source_ip, {"address": addr, "value": val})

        # ----- ot.protocol.write -----
        elif channel == "ot.protocol.write":
            protocol = data.get("protocol", "").lower()

            # IDS-012: DNP3 control
            if protocol == "dnp3":
                op = data.get("operation", "")
                if op in ("direct_operate", "select", "operate"):
                    self.fire_rule("IDS-012", source_ip, {"operation": op})

            # IDS-013: ENIP write
            elif protocol == "enip":
                self.fire_rule("IDS-013", source_ip, data)

            # IDS-014: IEC104 command
            elif protocol in ("iec104", "iec-60870-5-104"):
                ioa = data.get("ioa")
                value = data.get("value")
                self.fire_rule("IDS-014", source_ip, {"ioa": ioa, "value": value})

                # IDS-050: Power breaker open
                if ioa is not None and value is not None:
                    try:
                        if int(ioa) == 400 and int(value) == 0:
                            self.fire_rule("IDS-050", source_ip, {"ioa": 400, "value": 0})
                    except (ValueError, TypeError):
                        pass

            # IDS-040/041: PLC program upload/download
            if data.get("operation") == "upload":
                self.fire_rule("IDS-040", source_ip, data)
            elif data.get("operation") == "download":
                self.fire_rule("IDS-041", source_ip, data)

        # ----- sis.write -----
        elif channel == "sis.write":
            # IDS-011: Any SIS write is unauthorized
            self.fire_rule("IDS-011", source_ip, data)

            db = data.get("db")
            offset = data.get("offset")
            value = data.get("value")
            if db is not None and offset is not None and value is not None:
                try:
                    db_i = int(db)
                    off_i = int(offset)
                    val_i = int(value)
                except (ValueError, TypeError):
                    return

                # IDS-031: SIS trip threshold modified
                if db_i == 2 and off_i == 0:
                    self.fire_rule("IDS-031", source_ip, {"db": db_i, "offset": off_i, "value": val_i})

                # IDS-032: SIS trip delay increased >5000ms
                if db_i == 2 and off_i == 10 and val_i > 5000:
                    self.fire_rule("IDS-032", source_ip, {"db": db_i, "offset": off_i, "value": val_i})

        # ----- sis.maintenance -----
        elif channel == "sis.maintenance":
            enabled = data.get("enabled")
            if enabled is True or str(enabled).lower() == "true":
                self.fire_rule("IDS-030", source_ip, data)

        # ----- opcua.access -----
        elif channel == "opcua.access":
            operation = data.get("operation", "")
            node_path = data.get("node_path", "")

            # IDS-002: OPC-UA enumeration (browse)
            if operation == "browse" or "browse" in node_path.lower():
                self.fire_rule("IDS-002", source_ip, {"node_path": node_path})

            # IDS-051: OPC-UA write from DMZ
            if operation == "write":
                src = source_ip or data.get("source_zone", "")
                if "dmz" in src.lower() or src.startswith("10.0.2."):
                    self.fire_rule("IDS-051", source_ip, data)

        # ----- bms.access -----
        elif channel == "bms.access":
            operation = data.get("operation", "")

            # IDS-003: BACnet discovery
            if operation == "whois" or operation == "WhoIs":
                self.fire_rule("IDS-003", source_ip, data)

    # ------------------------------------------------------------------ #
    # Physics poller (chlorine monitoring)
    # ------------------------------------------------------------------ #

    def _physics_poller(self):
        while self._running:
            try:
                raw = self._r.get("physics:plant_state")
                if raw:
                    plant = json.loads(raw)
                    chem = plant.get("chemical", {})
                    chlorine = chem.get("chlorine_ppm", 0)

                    if chlorine > 6.0:
                        self.fire_rule("IDS-025-C", "", {"chlorine_ppm": chlorine})
                    elif chlorine > 4.0:
                        self.fire_rule("IDS-025-H", "", {"chlorine_ppm": chlorine})
                    elif chlorine > 2.0:
                        self.fire_rule("IDS-025-M", "", {"chlorine_ppm": chlorine})
            except Exception as exc:
                log.debug("physics poll error: %s", exc)

            time.sleep(PHYSICS_POLL_INTERVAL)


# ---------------------------------------------------------------------------
# Redis auto-detect helper
# ---------------------------------------------------------------------------

def _find_redis_host() -> str:
    """Try localhost first, then common gateway IPs."""
    for host in ["127.0.0.1", "10.0.3.1", "10.0.4.1", "192.168.1.1"]:
        try:
            r = redis.Redis(host=host, port=6379, socket_timeout=1)
            r.ping()
            r.close()
            return host
        except Exception:
            continue
    return "127.0.0.1"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )
    host = _find_redis_host()
    log.info("Using Redis at %s", host)
    engine = IDSEngine(redis_host=host)
    engine.start()
    log.info("IDS engine running with %d rules. Press Ctrl+C to stop.", len(engine.rules))
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        engine.stop()


if __name__ == "__main__":
    main()
