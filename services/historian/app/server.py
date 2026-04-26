"""Historian data server with SQL injection vulnerability."""
import os
import sqlite3
from flask import (Flask, render_template, request, redirect,
                   url_for, session, jsonify, g)

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "historian-key-2026")
DB_PATH = os.path.join(os.path.dirname(__file__), "historian.db")


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
        role TEXT
    );
    INSERT INTO users VALUES (1,'historian','hist0ry!','Historian Admin','admin');
    INSERT INTO users VALUES (2,'viewer','view2024','Read-Only Viewer','viewer');

    CREATE TABLE process_data (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT,
        source TEXT,
        tank_level REAL,
        chlorine_ppm REAL,
        ph REAL,
        temperature REAL,
        flow_rate REAL,
        filter_dp REAL,
        distribution_pressure REAL
    );

    CREATE TABLE credentials (
        id INTEGER PRIMARY KEY,
        service TEXT,
        host TEXT,
        port INTEGER,
        username TEXT,
        password TEXT,
        notes TEXT
    );
    INSERT INTO credentials VALUES (1,'SCADA HMI','10.0.3.10',8080,'operator','scada_op!','Main SCADA operator login');
    INSERT INTO credentials VALUES (2,'Engineering Workstation','10.0.3.20',8080,'openplc','openplc','OpenPLC web IDE default');
    INSERT INTO credentials VALUES (3,'Jump Host SSH','10.0.2.20',22,'maintenance','maint2024!','DMZ jump host for OT access');
    INSERT INTO credentials VALUES (4,'Safety HMI','10.0.5.202',8080,'safety_admin','s1s_adm1n!','Safety system admin');
    INSERT INTO credentials VALUES (5,'OPC-UA Gateway','10.0.3.20',4840,'anonymous','','Anonymous access enabled');
    INSERT INTO credentials VALUES (6,'Engineering WS SSH','10.0.3.20',22,'engineer','eng2024!','SSH access to engineering workstation');

    CREATE TABLE flags (
        id INTEGER PRIMARY KEY,
        flag TEXT,
        description TEXT
    );
    INSERT INTO flags VALUES (1,'SYSRUPT{sql1_1n_th3_h1st0r14n}','Found via SQL injection in query interface');
    """)
    db.commit()
    db.close()
    # Seed process data
    from seed_data import seed
    seed(DB_PATH)


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
        db = get_db()
        user = db.execute(
            "SELECT * FROM users WHERE username=? AND password=?",
            (username, password)
        ).fetchone()
        if user:
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            session["role"] = user["role"]
            return redirect(url_for("dashboard"))
        return render_template("login.html", error="Invalid credentials")
    return render_template("login.html")


@app.route("/dashboard")
def dashboard():
    if "user_id" not in session:
        return redirect(url_for("login"))
    db = get_db()
    count = db.execute("SELECT COUNT(*) FROM process_data").fetchone()[0]
    latest = db.execute(
        "SELECT * FROM process_data ORDER BY id DESC LIMIT 10"
    ).fetchall()
    return render_template("dashboard.html", count=count, latest=latest)


@app.route("/query", methods=["GET", "POST"])
def query():
    if "user_id" not in session:
        return redirect(url_for("login"))
    results = None
    columns = None
    error = None
    user_query = ""
    if request.method == "POST":
        source = request.form.get("source", "")
        user_query = source
        # VULNERABLE: direct string concatenation
        sql = f"SELECT * FROM process_data WHERE source = '{source}'"
        try:
            db = get_db()
            cur = db.execute(sql)
            results = cur.fetchall()
            if results:
                columns = results[0].keys()
        except Exception as e:
            error = str(e)
    return render_template("query.html", results=results, columns=columns,
                           error=error, user_query=user_query)


@app.route("/data")
def data_browser():
    if "user_id" not in session:
        return redirect(url_for("login"))
    db = get_db()
    page = int(request.args.get("page", 1))
    per_page = 50
    offset = (page - 1) * per_page
    rows = db.execute(
        "SELECT * FROM process_data ORDER BY timestamp DESC LIMIT ? OFFSET ?",
        (per_page, offset)
    ).fetchall()
    total = db.execute("SELECT COUNT(*) FROM process_data").fetchone()[0]
    pages = (total + per_page - 1) // per_page
    return render_template("data.html", rows=rows, page=page, pages=pages)


@app.route("/api/status")
def api_status():
    db = get_db()
    count = db.execute("SELECT COUNT(*) FROM process_data").fetchone()[0]
    latest = db.execute(
        "SELECT * FROM process_data ORDER BY id DESC LIMIT 1"
    ).fetchone()
    return jsonify({
        "status": "online",
        "records": count,
        "latest_timestamp": latest["timestamp"] if latest else None,
    })


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


init_db()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)
