#!/usr/bin/env python3
"""Display Game Hub -- Flask + SocketIO on :5555

Serves a single-page app designed for 320x240 ILI9341 in Chromium kiosk mode.
Reads state from Redis and pushes updates via Socket.IO every 500ms.
"""

from flask import Flask, render_template
from flask_socketio import SocketIO
import redis
import json
import time
import threading

app = Flask(__name__, template_folder="templates", static_folder="static")
app.config["SECRET_KEY"] = "sysrupt-display"
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="threading")

# Challenge data matching ctf/challenges/*.yml and ARCHITECTURE_VALIDATION.md
CHALLENGES = [
    {"id": 1, "name": "Perimeter Breach", "points": 100, "protocol": "HTTP"},
    {"id": 2, "name": "Intelligence Gathering", "points": 200, "protocol": "OPC-UA"},
    {"id": 3, "name": "Pivot to OT", "points": 300, "protocol": "SQLi+SSH"},
    {"id": 4, "name": "Building Recon", "points": 350, "protocol": "BACnet"},
    {"id": 5, "name": "Deep Protocol -- DNP3", "points": 400, "protocol": "DNP3"},
    {"id": 6, "name": "Deep Protocol -- ENIP", "points": 450, "protocol": "EtherNet/IP"},
    {"id": 7, "name": "Deep Protocol -- IEC104", "points": 500, "protocol": "IEC 104"},
    {"id": 8, "name": "Process Manipulation", "points": 600, "protocol": "Modbus"},
    {"id": 9, "name": "Safety Assault", "points": 800, "protocol": "S7comm"},
    {"id": 10, "name": "Full Compromise", "points": 1000, "protocol": "ALL"},
]
TOTAL_POINTS = sum(c["points"] for c in CHALLENGES)  # 4700


class DisplayStateMachine:
    """Manages screen state transitions for the 320x240 display."""

    BOOT = "boot"
    LOADING = "loading"
    IDLE = "idle"
    ACTIVE_PROGRESS = "progress"
    ACTIVE_HINT = "hint"
    ACTIVE_PLANT = "plant_mini"
    FLAG_CAPTURED = "flag_captured"
    ATTACK_ALERT = "attack_alert"
    SIS_TRIP = "sis_trip"
    VICTORY = "victory"

    ROTATION = [ACTIVE_PROGRESS, ACTIVE_HINT, ACTIVE_PLANT]
    ROTATION_TIMES = {ACTIVE_PROGRESS: 10, ACTIVE_HINT: 8, ACTIVE_PLANT: 5}

    def __init__(self):
        self.state = self.BOOT
        self.boot_time = time.time()
        self.rotation_index = 0
        self.rotation_timer = time.time()
        self.interrupt_state = None
        self.interrupt_expire = 0
        self.prev_flags = set()
        self.prev_attack_alerts = set()
        self.victory_locked = False

    def update(self, redis_state):
        """Called every 500ms with current Redis state. Returns current screen name."""
        now = time.time()

        # VICTORY is permanent UNLESS state has been reset
        if self.victory_locked:
            # Detect reset: score=0, no flags, no victory in Redis
            if (not redis_state.get("victory") and 
                redis_state.get("score", 0) == 0 and 
                not redis_state.get("flags_captured")):
                self.victory_locked = False
                self.state = self.IDLE
                self.prev_flags = set()
                self.prev_attack_alerts = set()
                return self.IDLE
            return self.VICTORY

        # Check victory
        if redis_state.get("victory"):
            self.victory_locked = True
            return self.VICTORY

        # BOOT -> IDLE after 5s
        if self.state == self.BOOT:
            if now - self.boot_time > 3:
                self.state = self.LOADING
            return self.BOOT

        # Check for SIS trip (stays until cleared)
        if redis_state.get("sis_tripped"):
            return self.SIS_TRIP

        # Check for new flag capture (10s interrupt)
        current_flags = set(redis_state.get("flags_captured", []))
        new_flags = current_flags - self.prev_flags
        if new_flags:
            self.prev_flags = current_flags
            self.interrupt_state = self.FLAG_CAPTURED
            self.interrupt_expire = now + 10
            self.state = self.ACTIVE_PROGRESS  # ensure we're in active mode

        # Check for attack alerts (5s interrupt, don't repeat same alert)
        attack_status = redis_state.get("attack_status", {})
        active_alerts = {k for k, v in attack_status.items() if v and k != "victory"}
        new_alerts = active_alerts - self.prev_attack_alerts
        if new_alerts and not self.interrupt_state:
            self.prev_attack_alerts = active_alerts
            self.interrupt_state = self.ATTACK_ALERT
            self.interrupt_expire = now + 5

        # Handle active interrupt
        if self.interrupt_state:
            if now < self.interrupt_expire:
                return self.interrupt_state
            self.interrupt_state = None

        # LOADING -> IDLE when startup complete or timeout
        if self.state == self.LOADING:
            startup_done = False
            try:
                cur = redis_state.get("startup_current", "")
                if cur == "complete":
                    startup_done = True
            except Exception:
                pass
            if startup_done or (now - self.boot_time > 90):
                self.state = self.IDLE
            return self.LOADING

        # Detect reset while in ACTIVE states: go back to IDLE
        if (self.state in self.ROTATION and 
            redis_state.get("score", 0) == 0 and
            not redis_state.get("flags_captured") and
            not redis_state.get("start_time")):
            self.state = self.IDLE
            self.prev_flags = set()
            self.prev_attack_alerts = set()
            return self.IDLE

        # IDLE -> ACTIVE when CTF starts
        if self.state == self.IDLE:
            if redis_state.get("start_time") or current_flags:
                self.state = self.ACTIVE_PROGRESS
                self.rotation_timer = now
            return self.IDLE

        # Active rotation
        current_screen = self.ROTATION[self.rotation_index]
        elapsed = now - self.rotation_timer
        if elapsed >= self.ROTATION_TIMES[current_screen]:
            self.rotation_index = (self.rotation_index + 1) % len(self.ROTATION)
            self.rotation_timer = now
            current_screen = self.ROTATION[self.rotation_index]

        return current_screen


class RedisStateReader:
    """Reads display-relevant state from Redis."""

    def __init__(self):
        self.r = None
        self._connect()

    def _connect(self):
        try:
            self.r = redis.Redis(
                host="127.0.0.1", port=6379,
                decode_responses=True, socket_timeout=1,
            )
            self.r.ping()
        except Exception:
            self.r = None

    def read(self):
        """Read all display-relevant state from Redis."""
        if not self.r:
            self._connect()
            if not self.r:
                return self._defaults()

        try:
            state = {}
            state["score"] = int(self.r.get("ctf:score") or 0)
            state["start_time"] = self.r.get("ctf:start_time")
            flags_raw = self.r.get("ctf:flags_captured")
            state["flags_captured"] = json.loads(flags_raw) if flags_raw else []

            plant_raw = self.r.get("physics:plant_state")
            if plant_raw:
                plant = json.loads(plant_raw)
                chem = plant.get("chemical", {})
                tank = plant.get("tank", {})
                power = plant.get("power", {})
                safety = plant.get("safety", {})
                state["chlorine_ppm"] = chem.get("chlorine_ppm", 1.5)
                state["ph"] = chem.get("ph", 7.2)
                state["tank_level"] = tank.get("level_pct", 60)
                state["voltage"] = power.get("voltage_v", 230)
                state["frequency"] = power.get("frequency_hz", 50.0)
                state["sis_tripped"] = safety.get("tripped", False)
                state["sis_maintenance"] = safety.get("maintenance_mode", False)
                state["attack_status"] = plant.get("attack_status", {})
                state["dosing_pump"] = chem.get("dosing_pump_on", False)
                state["pid_mode"] = chem.get("pid_mode", "auto")
            else:
                state.update(self._plant_defaults())

            victory_raw = self.r.get("physics:victory")
            state["victory"] = json.loads(victory_raw) if victory_raw else None

            # IDS state
            ids_threat = self.r.get("ids:threat_level")
            state["ids_threat_level"] = ids_threat or "NONE"
            ids_count = self.r.get("ids:alert_count")
            state["ids_alert_count"] = int(ids_count) if ids_count else 0

            # Check for new HIGH/CRITICAL alerts to trigger ATTACK_ALERT screen
            latest = self.r.get("ids:latest_alert")
            if latest:
                try:
                    alert = json.loads(latest)
                    if alert.get("severity") in ["HIGH", "CRITICAL"]:
                        state["attack_status"] = state.get("attack_status", {})
                        state["attack_status"]["ids_alert"] = True
                        state["attack_status"]["ids_alert_name"] = alert.get("name", "")
                        state["attack_status"]["ids_alert_severity"] = alert.get("severity", "")
                except (json.JSONDecodeError, TypeError):
                    pass

            return state
        except Exception:
            return self._defaults()

    def _defaults(self):
        d = {
            "score": 0, "flags_captured": [], "start_time": None,
            "victory": None,
        }
        d.update(self._plant_defaults())
        return d

    def _plant_defaults(self):
        return {
            "chlorine_ppm": 1.5, "ph": 7.2, "tank_level": 60,
            "voltage": 230, "frequency": 50.0,
            "sis_tripped": False, "sis_maintenance": False,
            "attack_status": {}, "dosing_pump": False, "pid_mode": "auto",
        }


# ---- singletons used by the background loop and tests ----
state_machine = DisplayStateMachine()
redis_reader = RedisStateReader()


def background_loop():
    """Push display state to all connected browsers every 500ms."""
    while True:
        redis_state = redis_reader.read()
        screen = state_machine.update(redis_state)

        flags = redis_state.get("flags_captured", [])
        level = len(flags) + 1
        current_challenge = CHALLENGES[min(level - 1, 9)]

        elapsed = ""
        if redis_state.get("start_time"):
            try:
                secs = int(time.time() - float(redis_state["start_time"]))
                if secs < 0:
                    secs = 0
                elapsed = f"{secs // 3600:02d}:{(secs % 3600) // 60:02d}:{secs % 60:02d}"
            except (ValueError, TypeError):
                elapsed = "00:00:00"

        payload = {
            "screen": screen,
            "score": redis_state["score"],
            "total_points": TOTAL_POINTS,
            "flags_captured": flags,
            "level": min(level, 10),
            "current_challenge": current_challenge,
            "challenges": CHALLENGES,
            "elapsed": elapsed,
            "chlorine_ppm": redis_state.get("chlorine_ppm", 1.5),
            "ph": redis_state.get("ph", 7.2),
            "tank_level": redis_state.get("tank_level", 60),
            "voltage": redis_state.get("voltage", 230),
            "frequency": redis_state.get("frequency", 50.0),
            "sis_tripped": redis_state.get("sis_tripped", False),
            "sis_maintenance": redis_state.get("sis_maintenance", False),
            "attack_status": redis_state.get("attack_status", {}),
            "victory": redis_state.get("victory"),
            "dosing_pump": redis_state.get("dosing_pump", False),
            "pid_mode": redis_state.get("pid_mode", "auto"),
            "ids_threat_level": redis_state.get("ids_threat_level", "NONE"),
            "ids_alert_count": redis_state.get("ids_alert_count", 0),
        }

        socketio.emit("display_state", payload)
        time.sleep(0.5)


def _get_wifi_ip():
    """Get the board's WiFi IP address."""
    try:
        import subprocess
        result = subprocess.run(
            ["ip", "-4", "addr", "show", "wlan0"],
            capture_output=True, text=True, timeout=2,
        )
        for line in result.stdout.split("\n"):
            if "inet " in line:
                return line.strip().split()[1].split("/")[0]
    except Exception:
        pass
    return None


@app.route("/")
def index():
    return render_template(
        "display.html", challenges=CHALLENGES, total_points=TOTAL_POINTS,
    )


@app.route("/api/state")
def api_state():
    """JSON endpoint for polling-based display updates."""
    import json as _json
    redis_state = redis_reader.read()
    screen = state_machine.update(redis_state)
    flags = redis_state.get("flags_captured", [])
    level = len(flags) + 1
    current_challenge = CHALLENGES[min(level - 1, 9)]
    elapsed = ""
    if redis_state.get("start_time"):
        try:
            secs = int(time.time() - float(redis_state["start_time"]))
            elapsed = f"{secs//3600:02d}:{(secs%3600)//60:02d}:{secs%60:02d}"
        except (ValueError, TypeError):
            elapsed = "00:00:00"
    # Get current hint
    hint_text = ""
    if screen == "hint":
        hints_data = {
            1: ["Check the page source carefully", "Default credentials are common", "Try admin as both username and password variant"],
            2: ["The data gateway allows browsing without credentials", "OPC-UA port 4840 - try anonymous", "Browse deep into PlantInfo"],
            3: ["The historian has a custom query - test input handling", "UNION SELECT when tables are unknown", "SSH tunneling through the jump host"],
            4: ["Not all OT devices are in the process zone", "UDP 47808 speaks building automation", "BACnet WhoIs reveals what is there"],
            5: ["Port 20000 is a different SCADA protocol", "DNP3 uses Select-Before-Operate", "Counter values might encode more than counts"],
            6: ["This PLC responds to UDP broadcasts on 44818", "EtherNet/IP uses CIP objects", "Custom object Class 0x64 Instance 1"],
            7: ["European grid SCADA protocol", "IEC 104 STARTDT on TCP 2404", "General Interrogation returns everything"],
            8: ["PLC-2 PID controller registers", "Manual mode plus max speed has a limit", "Download ladder logic from engineering WS"],
            9: ["Scan the engineering workstation local ports", "localhost:10102 leads somewhere", "S7comm DB2 has maintenance parameters"],
            10: ["Everything at once: alarms off plus safety bypassed", "The 5ppm override is in ladder logic", "Upload modified program then manual max speed"],
        }
        ch_hints = hints_data.get(min(level, 10), ["No hint available"])
        # Determine which hint based on elapsed time
        hint_idx = 0
        if redis_state.get("start_time"):
            try:
                elapsed_min = (time.time() - float(redis_state["start_time"])) / 60
                if elapsed_min > 45: hint_idx = 2
                elif elapsed_min > 30: hint_idx = 1
                else: hint_idx = 0
            except (ValueError, TypeError):
                hint_idx = 0
        hint_idx = min(hint_idx, len(ch_hints) - 1)
        hint_text = ch_hints[hint_idx]
    payload = {
        "screen": screen,
        "score": redis_state.get("score", 0),
        "total_points": TOTAL_POINTS,
        "flags_captured": flags,
        "level": min(level, 10),
        "current_challenge": current_challenge,
        "elapsed": elapsed,
        "chlorine_ppm": redis_state.get("chlorine_ppm", 1.5),
        "ph": redis_state.get("ph", 7.2),
        "tank_level": redis_state.get("tank_level", 60),
        "voltage": redis_state.get("voltage", 230),
        "frequency": redis_state.get("frequency", 50.0),
        "sis_tripped": redis_state.get("sis_tripped", False),
        "sis_maintenance": redis_state.get("sis_maintenance", False),
        "attack_status": redis_state.get("attack_status", {}),
        "victory": redis_state.get("victory"),
        "hint_text": hint_text,
        "startup_current": redis_state.get("startup_current", ""),
        "startup_phase": redis_state.get("startup_phase", ""),
        "wifi_ip": _get_wifi_ip(),
    }
    return _json.dumps(payload), 200, {"Content-Type": "application/json"}


def main():
    t = threading.Thread(target=background_loop, daemon=True)
    t.start()
    socketio.run(app, host="0.0.0.0", port=5555, debug=False, allow_unsafe_werkzeug=True)


if __name__ == "__main__":
    main()
