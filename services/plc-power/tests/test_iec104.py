"""Smoke tests for PLC-5 IEC 60870-5-104."""
import os
import socket
import struct
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
    "plc_power_server", os.path.join(SERVICE, "server.py")
)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


TEST_PORT = 12404


@pytest.fixture(scope="module")
def server():
    plc = mod.PowerFeedIEC104(bind_ip="127.0.0.1", bind_port=TEST_PORT)
    plc.start()
    time.sleep(1.0)
    yield plc
    plc.stop()
    time.sleep(0.2)


def test_server_running(server):
    assert server.server.is_running


def test_tcp_connect(server):
    s = socket.create_connection(("127.0.0.1", TEST_PORT), timeout=3)
    s.close()


def test_startdt_activation(server):
    """Send STARTDT act (U-format) and expect STARTDT con back."""
    s = socket.create_connection(("127.0.0.1", TEST_PORT), timeout=3)
    s.settimeout(3)
    # APCI: 0x68, length=4, control field 1=0x07 (STARTDT act), 2=0, 3=0, 4=0
    s.sendall(bytes([0x68, 0x04, 0x07, 0x00, 0x00, 0x00]))
    data = s.recv(32)
    s.close()
    assert len(data) >= 6
    assert data[0] == 0x68
    # STARTDT con control field 1 = 0x0B
    assert data[2] == 0x0B


def test_redis_state_published(server):
    time.sleep(5.5)
    if server._redis is None:
        pytest.skip("redis unavailable")
    status = server._redis.get("plc:power:status")
    assert status == "running"
    full = server._redis.get("plc:power:full_state")
    assert full is not None
    import json
    payload = json.loads(full)
    assert payload["protocol"] == "iec-60870-5-104"
    assert "voltage_v" in payload["measurements"]
