"""Smoke tests for Safety SIS - Flask HMI."""
import os
import sys
import time

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
SERVICE = os.path.abspath(os.path.join(HERE, ".."))
ROOT = os.path.abspath(os.path.join(SERVICE, "..", ".."))
for p in (ROOT, SERVICE):
    if p not in sys.path:
        sys.path.insert(0, p)

import importlib.util
spec = importlib.util.spec_from_file_location(
    "safety_hmi", os.path.join(SERVICE, "hmi.py")
)
hmi_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hmi_mod)


@pytest.fixture(scope="module")
def client():
    hmi_mod.app.config["TESTING"] = True
    with hmi_mod.app.test_client() as c:
        yield c


def _auth_headers():
    import base64
    creds = base64.b64encode(b"safety_admin:s1s_adm1n!").decode()
    return {"Authorization": f"Basic {creds}"}


def test_hmi_starts(client):
    """Flask app creates a test client."""
    assert client is not None


def test_hmi_auth_required(client):
    """GET / without auth returns 401."""
    resp = client.get("/")
    assert resp.status_code == 401


def test_hmi_shows_status(client):
    """GET / with auth returns 200 with SIS content."""
    resp = client.get("/", headers=_auth_headers())
    assert resp.status_code == 200
    assert b"SIS" in resp.data or b"SAFETY" in resp.data


def test_api_status(client):
    """GET /api/status returns JSON with status field."""
    resp = client.get("/api/status", headers=_auth_headers())
    assert resp.status_code == 200
    data = resp.get_json()
    assert "status" in data
