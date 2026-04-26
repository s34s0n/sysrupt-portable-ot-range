"""City Water Authority Corporate Portal."""
import os
import json
import sqlite3
from datetime import datetime
from flask import (Flask, render_template, request, redirect,
                   url_for, session, jsonify, send_from_directory, g)

app = Flask(__name__)
import secrets; app.secret_key = secrets.token_hex(16)  # random each restart - invalidates old sessions
DB_PATH = os.path.join(os.path.dirname(__file__), "corp.db")

def _find_redis():
    """Try candidate Redis hosts (namespace gateway IPs)."""
    import redis as _redis
    candidates = [
        os.environ.get("REDIS_HOST", "127.0.0.1"),
        "10.0.1.1",
        "10.0.2.1",
        "10.0.3.1",
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

try:
    import redis
    _r = _find_redis()
except Exception:
    _r = None


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    if os.path.exists(DB_PATH):
        return
    db = sqlite3.connect(DB_PATH)
    db.executescript("""
    CREATE TABLE users (
        id INTEGER PRIMARY KEY,
        username TEXT UNIQUE,
        password TEXT,
        name TEXT,
        role TEXT,
        email TEXT,
        department TEXT,
        notes TEXT,
        vpn_access INTEGER DEFAULT 0,
        last_login TEXT
    );
    INSERT INTO users VALUES (1,'admin','admin123','Administrator','System Administrator','admin@citywater.local','IT','Default admin account',1,'2026-04-08 08:00:00');
    INSERT INTO users VALUES (2,'jsmith','water2024','John Smith','Operations Manager','jsmith@citywater.local','Operations','Manages day-to-day plant operations',1,'2026-04-07 14:30:00');
    INSERT INTO users VALUES (3,'mchen','maint2024!','Mai Chen','Maintenance Engineer','mchen@citywater.local','Operations Technology','Responsible for PLC programming. Default access: openplc/openplc on engineering workstation.',1,'2026-04-08 09:15:00');
    INSERT INTO users VALUES (4,'rjones','p@ssw0rd','Robert Jones','IT Support','rjones@citywater.local','IT','Handles network infrastructure',0,'2026-04-06 16:45:00');

    CREATE TABLE files (
        id INTEGER PRIMARY KEY,
        filename TEXT,
        description TEXT,
        size TEXT
    );
    INSERT INTO files VALUES (1,'network_diagram_2025.pdf','Network architecture diagram','2.1 MB');
    INSERT INTO files VALUES (2,'maintenance_schedule_q2.xlsx','Q2 2026 maintenance windows','450 KB');
    INSERT INTO files VALUES (3,'vendor_contacts.csv','Approved vendor contact list','12 KB');
    INSERT INTO files VALUES (4,'scada_upgrade_proposal.docx','SCADA modernization proposal','1.8 MB');
    """)
    db.commit()
    db.close()


EMAILS = [
    {
        "id": 1,
        "from": "vendor-support@siemens-energy.com",
        "to": "mchen@citywater.local",
        "subject": "RE: Safety PLC Configuration Update",
        "date": "2026-04-05 10:23",
        "body": (
            "Hi Mai,\n\n"
            "As discussed, the S7-300 safety controller still has factory defaults "
            "from the bench test. Please refer to <strong>Chapter 7</strong> of the "
            "commissioning manual for the password reset procedure before the next "
            "maintenance window.\n\n"
            "Best regards,\nKlaus Weber\nSiemens Energy Support"
        ),
        "read": True
    },
    {
        "id": 2,
        "from": "rjones@citywater.local",
        "to": "all-staff@citywater.local",
        "subject": "Network Segmentation Update - Action Required",
        "date": "2026-04-04 14:10",
        "body": (
            "Team,\n\n"
            "The network segmentation project is complete. All zones are now "
            "isolated per the IEC 62443 reference architecture. The safety "
            "network is fully air-gapped from process.\n\n"
            "One thing to note: the engineering workstation may still have "
            "<em>remaining temporary bridges</em> from the commissioning phase. "
            "Please use the designated jump host for any remote access needs.\n\n"
            "- Robert Jones, IT Support"
        ),
        "read": False
    },
    {
        "id": 3,
        "from": "mchen@citywater.local",
        "to": "jsmith@citywater.local",
        "subject": "OPC-UA Server Access",
        "date": "2026-04-03 09:45",
        "body": (
            "John,\n\n"
            "The data gateway has been configured for the new monitoring "
            "integration. I left it in <strong>testing mode</strong> without "
            "credentials for now - will harden it once we finalize.\n\n"
            "Also, the historian query interface might need input sanitization. "
            "I'll add that to the hardening checklist.\n\n"
            "- Mai"
        ),
        "read": True
    },
]

FLAGS = {
    "SYSRUPT{p3r1m3t3r_br34ch3d}": {"id": 1, "name": "Perimeter Breach", "points": 100},
    "SYSRUPT{0pc_u4_1nt3l_g4th3r3d}": {"id": 2, "name": "Intelligence Gathering", "points": 200},
    "SYSRUPT{1ns1d3_th3_0t_n3tw0rk}": {"id": 3, "name": "Pivot to OT", "points": 300},
    "SYSRUPT{b4cn3t_bu1ld1ng_m4n4g3m3nt}": {"id": 4, "name": "Building Recon - BACnet", "points": 350},
    "SYSRUPT{dnp3_m4st3r_0p3r4t0r}": {"id": 5, "name": "Deep Protocol - DNP3", "points": 400},
    "SYSRUPT{c1p_3th3rn3t_1p_pwn3d}": {"id": 6, "name": "Deep Protocol - EtherNet/IP", "points": 450},
    "SYSRUPT{13c104_p0w3r_gr1d_4cc3ss}": {"id": 7, "name": "Deep Protocol - IEC 104", "points": 500},
    "SYSRUPT{m0dbu5_p1d_h4ck3d}": {"id": 8, "name": "Process Manipulation - Modbus", "points": 600},
    "SYSRUPT{s7_s4f3ty_byp4ss3d}": {"id": 9, "name": "Safety System Assault - S7comm", "points": 800},
    "SYSRUPT{pl4nt_c0mpr0m1s3d_g4m3_0v3r}": {"id": 10, "name": "Full Compromise - Stuxnet", "points": 1000},
}


@app.route("/")
def home():
    return render_template("home.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        db = get_db()
        user = db.execute(
            "SELECT * FROM users WHERE username=? AND password=?",
            (username, password)
        ).fetchone()
        if user:
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            session["name"] = user["name"]
            session["role"] = user["role"]
            # CTF: record login for auto-detection
            if _r and user["role"] == "System Administrator":
                try:
                    import json as _json
                    from datetime import datetime as _dt
                    _r.set("corp:admin_login", _json.dumps({
                        "timestamp": _dt.now().isoformat(),
                        "username": user["username"],
                        "source_ip": request.remote_addr,
                    }))
                except Exception:
                    pass
            return redirect(url_for("dashboard"))
        return render_template("login.html", error="Invalid credentials")
    return render_template("login.html")


@app.route("/dashboard")
def dashboard():
    if "user_id" not in session:
        return redirect(url_for("login"))
    return render_template("dashboard.html")


@app.route("/webmail")
def webmail():
    if "user_id" not in session:
        return redirect(url_for("login"))
    return render_template("webmail.html", emails=EMAILS)


@app.route("/admin")
def admin():
    if "user_id" not in session:
        return redirect(url_for("login"))
    if session.get("role") != "System Administrator":
        return render_template("admin.html", denied=True)
    flag = "SYSRUPT{p3r1m3t3r_br34ch3d}"
    return render_template("admin.html", denied=False, flag=flag)


@app.route("/files/")
def files_list():
    db = get_db()
    files = db.execute("SELECT * FROM files").fetchall()
    return render_template("files.html", files=files)


@app.route("/files/<filename>")
def files_download(filename):
    static_dir = os.path.join(os.path.dirname(__file__), "static", "files")
    os.makedirs(static_dir, exist_ok=True)
    if not os.path.exists(os.path.join(static_dir, filename)):
        return "File not found", 404
    return send_from_directory(static_dir, filename)


@app.route("/api/employee/<int:emp_id>")
def employee_api(emp_id):
    # NOTE: No authentication check - IDOR vulnerability
    db = get_db()
    emp = db.execute("SELECT * FROM users WHERE id=?", (emp_id,)).fetchone()
    if not emp:
        return jsonify({"error": "Employee not found"}), 404
    return jsonify({
        "id": emp["id"],
        "username": emp["username"],
        "name": emp["name"],
        "role": emp["role"],
        "email": emp["email"],
        "department": emp["department"],
        "notes": emp["notes"],
        "vpn_access": bool(emp["vpn_access"]),
        "last_login": emp["last_login"]
    })


@app.route("/contact")
def contact():
    return render_template("contact.html")


@app.route("/api/flag", methods=["POST"])
def submit_flag():
    data = request.get_json(silent=True)
    if not data or "flag" not in data:
        return jsonify({"success": False, "message": "Missing flag parameter"}), 400

    flag_val = data["flag"].strip()
    if flag_val not in FLAGS:
        return jsonify({"success": False, "message": "Invalid flag"}), 400

    flag_info = FLAGS[flag_val]

    if _r:
        captured = _r.smembers("ctf:flags_captured") or set()
        if str(flag_info["id"]) in captured:
            return jsonify({
                "success": False,
                "message": "Flag already captured"
            }), 200
        _r.sadd("ctf:flags_captured", str(flag_info["id"]))
        _r.incrby("ctf:score", flag_info["points"])
        score = int(_r.get("ctf:score") or 0)
    else:
        score = flag_info["points"]

    return jsonify({
        "success": True,
        "message": f"Correct! {flag_info['name']} ({flag_info['points']} pts)",
        "flag_id": flag_info["id"],
        "points": flag_info["points"],
        "total_score": score
    })


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))


init_db()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 80))
    app.run(host="0.0.0.0", port=port, debug=False)
