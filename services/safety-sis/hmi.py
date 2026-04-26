#!/usr/bin/env python3
"""
Safety SIS - Flask Web HMI
Displays SIS status, sensor readings, setpoints, trip history.
Runs on port 8082 inside svc-safety-hmi namespace.
"""

import json
import logging
import os
import signal
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(os.path.dirname(_HERE))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from flask import Flask, Response, jsonify, request

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
log = logging.getLogger("safety-hmi")

app = Flask(__name__)

AUTH_USER = "safety_admin"
AUTH_PASS = "s1s_adm1n!"

# ---------------------------------------------------------------------------
# Redis helper
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
    for host in ("10.0.5.1", "10.0.4.1", "10.0.3.1", "10.0.2.1",
                 "10.0.1.1", "172.17.0.1", "127.0.0.1"):
        try:
            r = _redis_mod.Redis(host=host, port=6379, decode_responses=True,
                                 socket_connect_timeout=0.5)
            r.ping()
            _redis = r
            return r
        except Exception:
            continue
    return None


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
def _check_auth():
    auth = request.authorization
    if not auth or auth.username != AUTH_USER or auth.password != AUTH_PASS:
        return False
    return True


def _auth_required(f):
    from functools import wraps

    @wraps(f)
    def decorated(*args, **kwargs):
        if not _check_auth():
            return Response(
                "Authentication required",
                401,
                {"WWW-Authenticate": 'Basic realm="Safety HMI"'},
            )
        return f(*args, **kwargs)

    return decorated


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.route("/")
@_auth_required
def index():
    r = _get_redis()
    status = "unknown"
    sensors = {"chlorine_ppm": 0, "ph": 0, "level_pct": 0}
    setpoints = {}
    trip_count = 0

    if r:
        try:
            status = r.get("sis:status") or "unknown"
            raw_sensors = r.get("sis:sensors")
            if raw_sensors:
                sensors = json.loads(raw_sensors)
            raw_sp = r.get("sis:setpoints")
            if raw_sp:
                setpoints = json.loads(raw_sp)
            trip_count = int(r.get("sis:trip_count") or 0)
        except Exception:
            pass

    status_upper = status.upper()
    if status == "tripped":
        status_color = "#ff4444"
        bg_pulse = "background: linear-gradient(135deg, #1a0000 0%, #330000 100%);"
    elif status == "maintenance":
        status_color = "#ffaa00"
        bg_pulse = "background: linear-gradient(135deg, #1a1500 0%, #332a00 100%);"
    else:
        status_color = "#44ff44"
        bg_pulse = "background: linear-gradient(135deg, #001a00 0%, #003300 100%);"

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>Safety SIS - HMI</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: 'Courier New', monospace; color: #e0e0e0;
         {bg_pulse} min-height: 100vh; padding: 20px; }}
  .header {{ text-align: center; margin-bottom: 30px; }}
  .header h1 {{ color: #ff6666; font-size: 24px; }}
  .header .subtitle {{ color: #888; font-size: 12px; }}
  .status-box {{ text-align: center; padding: 30px; margin: 20px auto;
                 max-width: 400px; border: 3px solid {status_color};
                 border-radius: 10px; }}
  .status-label {{ font-size: 14px; color: #888; }}
  .status-value {{ font-size: 48px; font-weight: bold;
                   color: {status_color}; }}
  .grid {{ display: grid; grid-template-columns: 1fr 1fr;
           gap: 20px; max-width: 800px; margin: 20px auto; }}
  .card {{ background: rgba(0,0,0,0.5); border: 1px solid #333;
           border-radius: 8px; padding: 15px; }}
  .card h3 {{ color: #ff6666; margin-bottom: 10px; font-size: 14px; }}
  .reading {{ display: flex; justify-content: space-between;
              padding: 5px 0; border-bottom: 1px solid #222; }}
  .reading .label {{ color: #888; }}
  .reading .value {{ color: #fff; font-weight: bold; }}
  .trip-count {{ text-align: center; margin-top: 10px; color: #888; }}
  .btn {{ padding: 10px 20px; border: 1px solid #ff4444;
          background: transparent; color: #ff4444; cursor: pointer;
          font-family: inherit; border-radius: 4px; margin-top: 15px; }}
  .btn:hover {{ background: #ff4444; color: #000; }}
  .actions {{ text-align: center; margin-top: 20px; }}
</style>
</head>
<body>
  <div class="header">
    <h1>SAFETY INSTRUMENTED SYSTEM</h1>
    <div class="subtitle">S7comm | Port 102 | SIS Controller</div>
  </div>

  <div class="status-box">
    <div class="status-label">SIS STATUS</div>
    <div class="status-value">{status_upper}</div>
  </div>

  <div class="grid">
    <div class="card">
      <h3>SENSOR READINGS</h3>
      <div class="reading">
        <span class="label">Chlorine (ppm)</span>
        <span class="value">{sensors.get('chlorine_ppm', 0):.2f}</span>
      </div>
      <div class="reading">
        <span class="label">pH</span>
        <span class="value">{sensors.get('ph', 0):.2f}</span>
      </div>
      <div class="reading">
        <span class="label">Level (%)</span>
        <span class="value">{sensors.get('level_pct', 0):.1f}</span>
      </div>
    </div>

    <div class="card">
      <h3>SETPOINTS</h3>
      <div class="reading">
        <span class="label">Cl High Trip</span>
        <span class="value">{setpoints.get('cl_trip_high', 5.0):.2f} ppm</span>
      </div>
      <div class="reading">
        <span class="label">Cl Low Trip</span>
        <span class="value">{setpoints.get('cl_trip_low', 0.1):.2f} ppm</span>
      </div>
      <div class="reading">
        <span class="label">pH High Trip</span>
        <span class="value">{setpoints.get('ph_trip_high', 9.0):.2f}</span>
      </div>
      <div class="reading">
        <span class="label">pH Low Trip</span>
        <span class="value">{setpoints.get('ph_trip_low', 6.0):.2f}</span>
      </div>
      <div class="reading">
        <span class="label">Level Trip</span>
        <span class="value">{setpoints.get('level_trip', 95)}%</span>
      </div>
      <div class="reading">
        <span class="label">Trip Delay</span>
        <span class="value">{setpoints.get('trip_delay_ms', 2000)} ms</span>
      </div>
    </div>
  </div>

  <div class="trip-count">Total Trips: {trip_count}</div>

  <div class="actions">
    <form method="POST" action="/reset">
      <button class="btn" type="submit">RESET TRIP</button>
    </form>
  </div>

  <script>
    setTimeout(function() {{ location.reload(); }}, 2000);
  </script>
</body>
</html>"""
    return html


@app.route("/reset", methods=["POST"])
@_auth_required
def reset():
    r = _get_redis()
    if r:
        try:
            r.publish("sis.command", json.dumps({"action": "reset"}))
        except Exception:
            pass
    return '<html><body style="background:#111;color:#0f0;text-align:center;padding:50px;font-family:monospace"><h2>Trip reset requested</h2><p><a href="/" style="color:#ff6666">Back to Dashboard</a></p></body></html>'


@app.route("/api/status")
@_auth_required
def api_status():
    r = _get_redis()
    result = {"status": "unknown", "armed": False, "tripped": False,
              "maintenance": False, "sensors": {}, "setpoints": {}}
    if r:
        try:
            status = r.get("sis:status") or "unknown"
            result["status"] = status
            result["armed"] = status == "armed"
            result["tripped"] = status == "tripped"
            result["maintenance"] = status == "maintenance"
            raw = r.get("sis:sensors")
            if raw:
                result["sensors"] = json.loads(raw)
            raw = r.get("sis:setpoints")
            if raw:
                result["setpoints"] = json.loads(raw)
            result["trip_count"] = int(r.get("sis:trip_count") or 0)
        except Exception:
            pass
    return jsonify(result)


def main():
    bind_ip = os.environ.get("HMI_BIND_IP", "0.0.0.0")
    bind_port = int(os.environ.get("HMI_BIND_PORT", "8082"))

    def _shutdown(signum, frame):
        sys.exit(0)

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    log.info("Safety HMI starting on %s:%d", bind_ip, bind_port)
    app.run(host=bind_ip, port=bind_port, debug=False)


if __name__ == "__main__":
    main()
