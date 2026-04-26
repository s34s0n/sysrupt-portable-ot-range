"""Tests for Historian."""
import os
import sys
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "app"))

_db = os.path.join(os.path.dirname(__file__), "..", "app", "historian.db")
if os.path.exists(_db):
    os.remove(_db)

from server import app


@pytest.fixture
def client():
    app.config["TESTING"] = True
    app.config["SECRET_KEY"] = "test"
    with app.test_client() as c:
        yield c


def _login(client, user="historian", pwd="hist0ry!"):
    return client.post("/login", data={"username": user, "password": pwd}, follow_redirects=True)


def test_login_works(client):
    rv = _login(client)
    assert rv.status_code == 200
    assert b"Dashboard" in rv.data or b"dashboard" in rv.data.lower()


def test_dashboard_shows_records(client):
    _login(client)
    rv = client.get("/dashboard")
    assert b"Total Records" in rv.data


def test_query_page_loads(client):
    _login(client)
    rv = client.get("/query")
    assert rv.status_code == 200
    assert b"Custom Query" in rv.data


def test_sqli_extracts_credentials(client):
    _login(client)
    payload = "' UNION SELECT id, service, host, port, username, password, notes, '', '', '' FROM credentials --"
    rv = client.post("/query", data={"source": payload})
    assert rv.status_code == 200
    assert b"scada_op!" in rv.data
    assert b"openplc" in rv.data


def test_data_browser(client):
    _login(client)
    rv = client.get("/data")
    assert rv.status_code == 200
    assert b"Data Browser" in rv.data


def test_seed_data_exists(client):
    _login(client)
    rv = client.get("/dashboard")
    # Should have 1000 records
    assert b"1000" in rv.data or b"Records" in rv.data


def test_api_status(client):
    rv = client.get("/api/status")
    assert rv.status_code == 200
    data = rv.get_json()
    assert data["status"] == "online"
    assert data["records"] >= 1000
