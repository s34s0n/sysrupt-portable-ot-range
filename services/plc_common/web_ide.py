"""
Flask web IDE for BasePLC instances. Mimics the OpenPLC v3 runtime
interface closely enough to be familiar to students who have seen it.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime
from functools import wraps

from flask import Flask, Response, jsonify, request, send_file

log = logging.getLogger(__name__)


def _check_auth(auth, username, password):
    return auth and auth.username == username and auth.password == password


def _auth_required(username, password):
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            auth = request.authorization
            if not _check_auth(auth, username, password):
                return Response(
                    "Authentication required",
                    401,
                    {"WWW-Authenticate": 'Basic realm="OpenPLC Runtime"'},
                )
            return f(*args, **kwargs)

        return wrapper

    return decorator


BASE_CSS = """
<style>
  body { background:#1a1a1a; color:#e0e0e0; font-family:Consolas,monospace;
         margin:0; padding:20px; }
  h1,h2 { color:#00ff88; border-bottom:1px solid #00ff88; padding-bottom:6px; }
  a { color:#00ff88; text-decoration:none; }
  a:hover { text-decoration:underline; }
  table { border-collapse:collapse; width:100%; margin-top:10px;
          background:#0f0f0f; }
  th,td { border:1px solid #333; padding:6px 10px; text-align:left;
          font-size:13px; }
  th { background:#222; color:#00ff88; }
  .nav { background:#0a0a0a; padding:10px 20px; border-bottom:2px solid #00ff88;
         margin:-20px -20px 20px -20px; }
  .nav a { margin-right:20px; font-weight:bold; }
  .brand { color:#00ff88; font-size:18px; font-weight:bold; }
  .status-running { color:#00ff88; }
  .status-stopped { color:#ff4444; }
  pre { background:#0a0a0a; padding:15px; border:1px solid #333;
        overflow:auto; color:#c8c8c8; }
  .btn { display:inline-block; background:#00ff88; color:#000; padding:6px 14px;
         border-radius:2px; margin:4px; }
</style>
"""


def _nav(plc_id):
    return f"""
    <div class="nav">
      <span class="brand">OpenPLC v3 &mdash; RUNTIME</span>
      &nbsp;&nbsp;
      <a href="/">Dashboard</a>
      <a href="/program">Program</a>
      <a href="/registers.html">Monitoring</a>
      <a href="/start">Start</a>
      <a href="/stop">Stop</a>
      <span style="float:right; color:#888;">plc:{plc_id}</span>
    </div>
    """


class PLCWebIDE:
    def __init__(
        self,
        plc_instance,
        st_file_path,
        bind_ip,
        bind_port=8080,
        username="openplc",
        password="openplc",
    ):
        self.plc = plc_instance
        self.st_file_path = st_file_path
        self.bind_ip = bind_ip
        self.bind_port = bind_port
        self.username = username
        self.password = password
        self._thread = None
        self._server = None

        self.app = Flask(f"plcwebide-{plc_instance.PLC_ID}")
        self.app.config["MAX_CONTENT_LENGTH"] = 1 * 1024 * 1024
        self._register_routes()

    # ------------------------------------------------------------------ #
    def _register_routes(self):
        req_auth = _auth_required(self.username, self.password)
        app = self.app
        plc = self.plc
        st_path = self.st_file_path

        @app.route("/")
        @req_auth
        def index():
            status_cls = (
                "status-running" if plc.status == "running" else "status-stopped"
            )
            body = f"""<!DOCTYPE html><html><head><title>{plc.PLC_NAME}</title>
            {BASE_CSS}</head><body>{_nav(plc.PLC_ID)}
            <h1>{plc.PLC_NAME}</h1>
            <table>
              <tr><th>PLC ID</th><td>{plc.PLC_ID}</td></tr>
              <tr><th>Bind</th><td>{plc.BIND_IP}:{plc.BIND_PORT}</td></tr>
              <tr><th>Status</th>
                  <td class="{status_cls}">{plc.status.upper()}</td></tr>
              <tr><th>Scan count</th><td>{plc.scan_count}</td></tr>
              <tr><th>Scan time</th><td>{plc.scan_time_ms:.2f} ms</td></tr>
              <tr><th>Scan period</th>
                  <td>{plc.SCAN_PERIOD_S*1000:.0f} ms</td></tr>
              <tr><th>Program file</th><td>{st_path}</td></tr>
            </table>
            <h2>Actions</h2>
            <a class="btn" href="/program">View Program</a>
            <a class="btn" href="/program/download">Download .st</a>
            <a class="btn" href="/registers.html">Monitor Registers</a>
            </body></html>"""
            return body

        @app.route("/program")
        @req_auth
        def program_view():
            try:
                with open(st_path) as f:
                    content = f.read()
            except Exception as exc:
                content = f"(error reading program: {exc})"
            from html import escape

            body = f"""<!DOCTYPE html><html><head>
            <title>Program &mdash; {plc.PLC_NAME}</title>{BASE_CSS}</head>
            <body>{_nav(plc.PLC_ID)}
            <h1>Program &mdash; {os.path.basename(st_path)}</h1>
            <a class="btn" href="/program/download">Download</a>
            <form method="POST" action="/program/upload"
                  enctype="multipart/form-data" style="display:inline-block;">
              <input type="file" name="file" accept=".st">
              <input type="submit" class="btn" value="Upload">
            </form>
            <pre>{escape(content)}</pre>
            </body></html>"""
            return body

        @app.route("/program/download")
        @req_auth
        def program_download():
            return send_file(
                st_path,
                as_attachment=True,
                download_name=os.path.basename(st_path),
                mimetype="text/plain",
            )

        @app.route("/program/upload", methods=["POST"])
        @req_auth
        def program_upload():
            f = request.files.get("file")
            if f is None or f.filename == "":
                return ("No file provided", 400)
            ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            target_dir = os.path.dirname(os.path.abspath(st_path))
            target = os.path.join(target_dir, f"uploaded_{ts}.st")
            f.save(target)

            # log event
            if plc._redis is not None:
                try:
                    plc._redis.publish(
                        "plc.program.uploaded",
                        json.dumps(
                            {
                                "plc_id": plc.PLC_ID,
                                "filename": f.filename,
                                "saved_to": target,
                                "timestamp": datetime.utcnow().isoformat(),
                            }
                        ),
                    )
                except Exception:
                    pass
            return (
                "Program uploaded successfully. "
                "PLC restart required for changes to take effect.\n",
                200,
            )

        @app.route("/registers")
        @req_auth
        def registers_json():
            hr, ir, co, di = plc._snapshot()
            return jsonify(
                {
                    "holding": hr,
                    "inputs": ir,
                    "coils": co,
                    "discrete": di,
                    "scan_count": plc.scan_count,
                    "scan_time_ms": plc.scan_time_ms,
                    "status": plc.status,
                }
            )

        @app.route("/registers.html")
        @req_auth
        def registers_html():
            hr, ir, co, di = plc._snapshot()

            def rows(label, vals, prefix):
                out = ""
                for i, v in enumerate(vals):
                    out += f"<tr><td>{prefix}{i}</td><td>{v}</td></tr>"
                return out

            body = f"""<!DOCTYPE html><html><head>
            <title>Monitor &mdash; {plc.PLC_NAME}</title>
            <meta http-equiv="refresh" content="1">
            {BASE_CSS}</head><body>{_nav(plc.PLC_ID)}
            <h1>Register Monitor</h1>
            <p>Scan #{plc.scan_count} &middot; {plc.scan_time_ms:.2f} ms
               &middot; status: {plc.status}</p>
            <h2>Holding Registers</h2>
            <table><tr><th>Addr</th><th>Value</th></tr>
              {rows("HR", hr, "%MW")}</table>
            <h2>Input Registers</h2>
            <table><tr><th>Addr</th><th>Value</th></tr>
              {rows("IR", ir, "%IW")}</table>
            <h2>Coils</h2>
            <table><tr><th>Addr</th><th>Value</th></tr>
              {rows("CO", co, "%QX0.")}</table>
            <h2>Discrete Inputs</h2>
            <table><tr><th>Addr</th><th>Value</th></tr>
              {rows("DI", di, "%IX0.")}</table>
            </body></html>"""
            return body

        @app.route("/start")
        @req_auth
        def start_route():
            plc.scan_resume()
            return "PLC scan resumed\n"

        @app.route("/stop")
        @req_auth
        def stop_route():
            plc.scan_pause()
            return "PLC scan paused\n"

    # ------------------------------------------------------------------ #
    def run(self):
        from werkzeug.serving import make_server

        self._server = make_server(
            self.bind_ip, self.bind_port, self.app, threaded=True
        )
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name=f"webide-{self.plc.PLC_ID}",
            daemon=True,
        )
        self._thread.start()
        log.info(
            "[%s] Web IDE on http://%s:%d",
            self.plc.PLC_ID,
            self.bind_ip,
            self.bind_port,
        )

    def stop(self):
        if self._server is not None:
            try:
                self._server.shutdown()
            except Exception:
                pass
