"""SCADA HMI - Live process dashboard with WebSocket updates."""
import os
import json
import time
import threading
from flask import (Flask, render_template, request, redirect,
                   url_for, session, jsonify)
from flask_socketio import SocketIO

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "scada-hmi-key-2026")
socketio = SocketIO(app, cors_allowed_origins="*")

def _find_redis():
    """Try candidate Redis hosts (namespace gateway IPs)."""
    import redis as _redis
    candidates = [
        os.environ.get("REDIS_HOST", "127.0.0.1"),
        "10.0.3.1",
        "10.0.1.1",
        "10.0.2.1",
    ]
    for host in candidates:
        try:
            r = _redis.Redis(host=host, port=6379, decode_responses=True,
                             socket_timeout=1, socket_connect_timeout=1)
            r.ping()
            return r
        except Exception:
            continue
    return None

_r = None
try:
    import redis
    _r = _find_redis()
except Exception:
    _r = None

# Default plant state when Redis is unavailable
DEFAULT_STATE = {
    "tank_level": 72.0,
    "chlorine_ppm": 2.5,
    "ph": 7.2,
    "temperature": 18.5,
    "flow_rate": 850.0,
    "filter_dp": [8.2, 7.5, 9.1, 6.8],
    "distribution_pressure": 62.0,
    "pump1_running": True,
    "pump2_running": False,
    "pid_mode": "auto",
    "pid_setpoint": 2.5,
    "power_status": "normal",
    "sis_status": "armed",
    "alarm_active": False,
    "alarm_inhibit": False,
    "timestamp": "2026-04-08T10:30:00",
}

alarms_log = []


def get_plant_state():
    """Read nested physics state from Redis and flatten for HMI display."""
    if _r:
        try:
            raw = _r.get("physics:plant_state")
            if raw:
                d = json.loads(raw)
                # Flatten nested structure into HMI-friendly format
                tank = d.get("tank", {})
                chem = d.get("chemical", {})
                p1 = d.get("pump1", {})
                p2 = d.get("pump2", {})
                filt = d.get("filtration", {})
                pwr = d.get("power", {})
                safety = d.get("safety", {})
                attack = d.get("attack_status", {})
                pid = chem.get("pid", {})

                filter_dp = [b.get("dp_kpa", 0) for b in filt.get("beds", [])]
                while len(filter_dp) < 4:
                    filter_dp.append(0)

                cl = chem.get("chlorine_ppm", 2.5)
                indicators = attack.get("indicators", {})

                return {
                    "tank_level": tank.get("level_pct", 72.0),
                    "chlorine_ppm": cl,
                    "ph": chem.get("ph", 7.2),
                    "temperature": 18.5,
                    "flow_rate": p1.get("flow_lpm", 0) + p2.get("flow_lpm", 0),
                    "filter_dp": filter_dp,
                    "distribution_pressure": 62.0,
                    "pump1_running": p1.get("running", False),
                    "pump2_running": p2.get("running", False),
                    "pid_mode": "manual" if d.get("plc_inputs", {}).get("pid_mode", 1) == 0 else "auto",
                    "pid_setpoint": 1.5,
                    "power_status": "normal" if pwr.get("breaker_closed", True) else "failure",
                    "sis_status": _r.get("sis:status") or safety.get("sis_status", "armed"),
                    "alarm_active": cl > 4.0,
                    "alarm_inhibit": safety.get("maintenance_mode", False) or (_r.get("sis:status") == "maintenance"),
                    "timestamp": d.get("timestamp", ""),
                }
        except Exception:
            pass
    return DEFAULT_STATE.copy()


def _get_distribution_state():
    """Read distribution PLC state from Redis."""
    if _r:
        try:
            tags_raw = _r.get("plc:distribution:tags")
            if tags_raw:
                tags = json.loads(tags_raw)
                return {
                    "pressure": tags.get("OUTLET_PRESSURE", [0])[0] / 10.0,
                    "alarm_enable": bool(tags.get("ALARM_ENABLE", [1])[0]),
                    "alarm_threshold": tags.get("ALARM_THRESHOLD", [800])[0] / 10.0,
                    "mode": "MANUAL" if tags.get("MODE_SELECT", [1])[0] == 0 else "AUTO",
                    "pump_speed": tags.get("BOOSTER_PUMP_SPEED", [0])[0],
                }
        except Exception:
            pass
    return {"pressure": 42.0, "alarm_enable": True, "alarm_threshold": 80.0,
            "mode": "AUTO", "pump_speed": 62}


def background_publisher():
    """Push plant state to all WebSocket clients every 500ms."""
    while True:
        try:
            state = get_plant_state()
            dist = _get_distribution_state()
            state["dist_pressure"] = dist["pressure"]
            state["dist_alarm_enable"] = dist["alarm_enable"]
            state["dist_mode"] = dist["mode"]
            socketio.emit("plant_state", state)

            ts = state.get("timestamp", "") or time.strftime("%Y-%m-%d %H:%M:%S")

            # Chlorine alarm
            cl = state.get("chlorine_ppm", 2.5)
            if cl > 4.0 and not state.get("alarm_inhibit", False):
                entry = {
                    "time": ts,
                    "level": "HIGH" if cl > 6.0 else "WARNING",
                    "message": f"Chlorine level elevated: {cl:.2f} ppm",
                }
                if len(alarms_log) == 0 or alarms_log[-1]["message"] != entry["message"]:
                    alarms_log.append(entry)
                    if len(alarms_log) > 100:
                        alarms_log.pop(0)

            # Distribution pressure alarm
            dp = dist["pressure"]
            dt = dist["alarm_threshold"]
            if dp > dt and dist["alarm_enable"]:
                entry = {
                    "time": ts,
                    "level": "CRITICAL",
                    "message": f"Distribution OVERPRESSURE: {dp:.1f} PSI (threshold: {dt:.1f})",
                }
                if len(alarms_log) == 0 or alarms_log[-1]["message"] != entry["message"]:
                    alarms_log.append(entry)
                    if len(alarms_log) > 100:
                        alarms_log.pop(0)

            # Distribution alarm disabled warning
            if not dist["alarm_enable"]:
                entry = {
                    "time": ts,
                    "level": "WARNING",
                    "message": "Distribution pressure alarm DISABLED",
                }
                if len(alarms_log) == 0 or alarms_log[-1]["message"] != entry["message"]:
                    alarms_log.append(entry)
                    if len(alarms_log) > 100:
                        alarms_log.pop(0)

            # Mode change warning
            if dist["mode"] == "MANUAL":
                entry = {
                    "time": ts,
                    "level": "WARNING",
                    "message": f"Distribution PLC in MANUAL mode - pump speed {dist['pump_speed']}%",
                }
                if len(alarms_log) == 0 or alarms_log[-1]["message"] != entry["message"]:
                    alarms_log.append(entry)
                    if len(alarms_log) > 100:
                        alarms_log.pop(0)
        except Exception:
            pass
        time.sleep(0.5)


@app.route("/")
def index():
    if "user_id" not in session:
        return redirect(url_for("login"))
    return redirect(url_for("dashboard"))


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        if username == "operator" and password == "scada_op!":
            session["user_id"] = 1
            session["username"] = "operator"
            # CTF: record login for auto-detection
            if _r:
                try:
                    import json as _json
                    from datetime import datetime as _dt
                    _r.set("scada:hmi_login", _json.dumps({
                        "timestamp": _dt.now().isoformat(),
                        "username": "operator",
                        "source_ip": request.remote_addr,
                    }))
                except Exception:
                    pass
            return redirect(url_for("dashboard"))
        return render_template("login.html", error="Access denied")
    return render_template("login.html")


@app.route("/dashboard")
def dashboard():
    if "user_id" not in session:
        return redirect(url_for("login"))
    return render_template("dashboard.html")


@app.route("/distribution")
def distribution():
    if "user_id" not in session:
        return redirect(url_for("login"))
    return render_template("distribution.html")


@app.route("/api/distribution")
def api_distribution():
    """JSON endpoint for distribution PLC state. Flag only returned when CH-06 is solved."""
    result = {
        "pressure": 42.0, "flow": 85.0, "reservoir": 75.0,
        "pump_speed": 62, "mode": "AUTO", "alarm_enable": True,
        "alarm_threshold": 80.0, "pressure_sp": 42.0,
    }
    if _r:
        try:
            tags_raw = _r.get("plc:distribution:tags")
            if tags_raw:
                tags = json.loads(tags_raw)
                result = {
                    "pressure": tags.get("OUTLET_PRESSURE", [0])[0] / 10.0,
                    "flow": tags.get("BOOSTER_FLOW", [0])[0] / 10.0,
                    "reservoir": tags.get("RESERVOIR_LEVEL", [0])[0] / 100.0,
                    "pump_speed": tags.get("BOOSTER_PUMP_SPEED", [0])[0],
                    "mode": "AUTO" if tags.get("MODE_SELECT", [1])[0] == 1 else "MANUAL",
                    "alarm_enable": bool(tags.get("ALARM_ENABLE", [1])[0]),
                    "alarm_threshold": tags.get("ALARM_THRESHOLD", [800])[0] / 10.0,
                    "pressure_sp": tags.get("PRESSURE_SP", [420])[0] / 10.0,
                }
            # Only include flag if CH-06 is actually solved in CTF engine
            ch6 = _r.get("ctf:challenge:6")
            if ch6:
                result["flag"] = "SYSRUPT{s1l3nt_0v3rpr3ssur3}"
        except Exception:
            pass
    return jsonify(result)


@app.route("/power")
def power():
    if "user_id" not in session:
        return redirect(url_for("login"))
    return render_template("power.html")


@app.route("/api/power")
def api_power():
    """JSON endpoint for power substation state."""
    result = {
        "main_breaker": True, "bus_tie": False, "feeder_a": True, "feeder_b": True,
        "voltage": 230.0, "current": 42.5, "power": 9200, "frequency": 50.0,
    }
    if _r:
        try:
            raw = _r.get("plc:power:full_state")
            if raw:
                d = json.loads(raw)
                sp = d.get("single_points", {})
                ms = d.get("measurements", {})
                result = {
                    "main_breaker": sp.get("main_breaker", True),
                    "bus_tie": sp.get("bus_tie", False),
                    "feeder_a": sp.get("feeder_a", True),
                    "feeder_b": sp.get("feeder_b", True),
                    "voltage": ms.get("voltage_v", 230.0),
                    "current": ms.get("current_a", 42.5),
                    "power": ms.get("p_active_w", 9200),
                    "frequency": ms.get("frequency_hz", 50.0),
                }
            # Flag only if CH-07 is solved
            ch7 = _r.get("ctf:challenge:7")
            if ch7:
                result["flag"] = "SYSRUPT{13c104_bl4ck0ut}"
        except Exception:
            pass
    return jsonify(result)


@app.route("/alarms")
def alarms():
    if "user_id" not in session:
        return redirect(url_for("login"))
    return render_template("alarms.html", alarms=list(reversed(alarms_log[-50:])))


@app.route("/api/status")
def api_status():
    state = get_plant_state()
    # Include flags if solved
    if _r:
        try:
            if _r.get("ctf:challenge:8"):
                state["flag_ch8"] = "SYSRUPT{m0dbu5_p1d_h4ck3d}"
            if _r.get("ctf:challenge:9"):
                state["flag_ch9"] = "SYSRUPT{s7_s4f3ty_byp4ss3d}"
            if _r.get("ctf:challenge:10"):
                state["flag_ch10"] = "SYSRUPT{pl4nt_c0mpr0m1s3d}"
        except Exception:
            pass
    return jsonify(state)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@socketio.on("connect")
def on_connect():
    state = get_plant_state()
    socketio.emit("plant_state", state)


if __name__ == "__main__":
    t = threading.Thread(target=background_publisher, daemon=True)
    t.start()
    port = int(os.environ.get("PORT", 8080))
    socketio.run(app, host="0.0.0.0", port=port, debug=False, allow_unsafe_werkzeug=True)
