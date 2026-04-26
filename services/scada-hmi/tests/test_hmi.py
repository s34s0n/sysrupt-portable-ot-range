"""Tests for SCADA HMI."""
import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))
from server import app


@pytest.fixture
def client():
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "test"
    with app.test_client() as c:
        yield c


def _login(client):
    return client.post("/login", data={"username": "operator", "password": "scada_op!"}, follow_redirects=True)


def test_login_page(client):
    rv = client.get("/login")
    assert rv.status_code == 200
    assert b"SCADA" in rv.data


def test_login_success(client):
    rv = _login(client)
    assert rv.status_code == 200


def test_dashboard_has_svg(client):
    _login(client)
    rv = client.get("/dashboard")
    assert rv.status_code == 200
    assert b"process-svg" in rv.data
    assert b"tank-water" in rv.data
    assert b"pump1" in rv.data
    assert b"CHEMICAL DOSING" in rv.data


def test_trends_page(client):
    _login(client)
    rv = client.get("/trends")
    assert rv.status_code == 200
    assert b"Trends" in rv.data


def test_alarms_page(client):
    _login(client)
    rv = client.get("/alarms")
    assert rv.status_code == 200
    assert b"Alarm Log" in rv.data


def test_api_status(client):
    rv = client.get("/api/status")
    assert rv.status_code == 200
    data = rv.get_json()
    assert "tank_level" in data or "tank" in data
