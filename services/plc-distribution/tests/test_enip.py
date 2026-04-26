"""Smoke tests for PLC-4 EtherNet/IP (cpppo-backed)."""
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
    "plc_distribution_server", os.path.join(SERVICE, "server.py")
)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


TEST_PORT = 44820


@pytest.fixture(scope="module")
def server():
    plc = mod.DistributionENIP(bind_ip="127.0.0.1", bind_port=TEST_PORT)
    ok = plc.start()
    assert ok, "cpppo failed to start"
    time.sleep(0.5)
    yield plc
    plc.stop()
    time.sleep(0.2)


def test_server_subprocess_alive(server):
    assert server._proc is not None
    assert server._proc.poll() is None


def test_tcp_port_accepts_connection(server):
    s = socket.create_connection(("127.0.0.1", TEST_PORT), timeout=3)
    s.close()


def test_register_session(server):
    s = socket.create_connection(("127.0.0.1", TEST_PORT), timeout=3)
    s.settimeout(3)
    # EtherNet/IP RegisterSession encapsulation header
    # command=0x0065, length=4, session=0, status=0, context=0, options=0
    # data: protocol version (2 bytes) + options flags (2 bytes)
    header = struct.pack("<HHIIQI", 0x0065, 4, 0, 0, 0, 0)
    data = struct.pack("<HH", 1, 0)
    s.sendall(header + data)
    resp = s.recv(4096)
    s.close()
    assert len(resp) >= 24
    cmd, length, session, status = struct.unpack("<HHII", resp[:12])
    assert cmd == 0x0065
    assert status == 0
    assert session != 0


def test_redis_state_published(server):
    time.sleep(2.2)
    if server._redis is None:
        pytest.skip("redis unavailable")
    status = server._redis.get("plc:distribution:status")
    assert status == "running"
    full = server._redis.get("plc:distribution:full_state")
    assert full is not None
    import json
    payload = json.loads(full)
    assert payload["protocol"] == "ethernet-ip"
    assert "OUTLET_PRESSURE" in payload["tags"]
