"""Tests for Corporate Portal."""
import os
import sys
import tempfile
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

# Remove any pre-existing DB so tests get a clean one
_db = os.path.join(os.path.dirname(__file__), "..", "app", "corp.db")
if os.path.exists(_db):
    os.remove(_db)

from server import app


@pytest.fixture
def client():
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "test"
    with app.test_client() as c:
        yield c


def _login(client, user="admin", pwd="admin123"):
    return client.post("/login", data={"username": user, "password": pwd}, follow_redirects=True)


def test_homepage_loads(client):
    rv = client.get("/")
    assert rv.status_code == 200
    assert b"City Water Authority" in rv.data


def test_login_success(client):
    rv = _login(client)
    assert rv.status_code == 200
    assert b"Dashboard" in rv.data or b"dashboard" in rv.data.lower()


def test_login_failure(client):
    rv = client.post("/login", data={"username": "bad", "password": "bad"}, follow_redirects=True)
    assert b"Invalid" in rv.data


def test_idor_returns_employee(client):
    rv = client.get("/api/employee/3")
    assert rv.status_code == 200
    data = rv.get_json()
    assert data["name"] == "Mai Chen"
    assert "openplc" in data["notes"]


def test_idor_no_auth_needed(client):
    rv = client.get("/api/employee/1")
    assert rv.status_code == 200
    assert rv.get_json()["username"] == "admin"


def test_webmail_requires_login(client):
    rv = client.get("/webmail", follow_redirects=True)
    assert b"Login" in rv.data or b"login" in rv.data.lower()


def test_webmail_content(client):
    _login(client)
    rv = client.get("/webmail")
    assert rv.status_code == 200
    assert b"factory defaults" in rv.data or b"Chapter 7" in rv.data
    assert b"temporary bridges" in rv.data or b"segmentation" in rv.data
    assert b"testing mode" in rv.data.lower() or b"sanitization" in rv.data.lower()


def test_admin_flag(client):
    _login(client)
    rv = client.get("/admin")
    assert b"SYSRUPT{p3r1m3t3r_br34ch3d}" in rv.data


def test_admin_denied_for_non_admin(client):
    _login(client, "jsmith", "water2024")
    rv = client.get("/admin")
    assert b"denied" in rv.data.lower()


def test_files_directory(client):
    rv = client.get("/files/")
    assert rv.status_code == 200
    assert b"network_diagram" in rv.data


def test_contact_page(client):
    rv = client.get("/contact")
    assert rv.status_code == 200
    assert b"555" in rv.data


def test_html_comments_hints(client):
    rv = client.get("/")
    assert b"employee API" in rv.data or b"TODO" in rv.data


def test_flag_submission_valid(client):
    rv = client.post("/api/flag",
                     json={"flag": "SYSRUPT{p3r1m3t3r_br34ch3d}"},
                     content_type="application/json")
    data = rv.get_json()
    assert data["success"] is True
    assert data["points"] == 100


def test_flag_submission_invalid(client):
    rv = client.post("/api/flag", json={"flag": "wrong"}, content_type="application/json")
    data = rv.get_json()
    assert data["success"] is False


def test_flag_missing_param(client):
    rv = client.post("/api/flag", json={}, content_type="application/json")
    assert rv.status_code == 400
