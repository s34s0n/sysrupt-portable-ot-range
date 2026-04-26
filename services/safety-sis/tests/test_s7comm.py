"""Smoke tests for Safety SIS - S7comm server."""
import json
import os
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
    "safety_sis_server", os.path.join(SERVICE, "server.py")
)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

TEST_PORT = 11020

import snap7


@pytest.fixture(scope="module")
def sis_server():
    sis = mod.SafetySIS(bind_ip="127.0.0.1", bind_port=TEST_PORT)
    sis.start()
    time.sleep(1.0)
    yield sis
    sis.stop()
    time.sleep(0.3)


@pytest.fixture
def s7client(sis_server):
    c = snap7.client.Client()
    c.connect("127.0.0.1", 0, 1, TEST_PORT)
    yield c
    try:
        c.disconnect()
    except Exception:
        pass


def test_server_starts(sis_server):
    assert sis_server.running


def test_cotp_connect(sis_server):
    """TCP connect to server port succeeds."""
    import socket
    s = socket.create_connection(("127.0.0.1", TEST_PORT), timeout=3)
    s.close()


def test_s7_setup(s7client):
    """snap7 client connects and completes S7 setup."""
    assert s7client.get_connected()


def test_read_db1(s7client, sis_server):
    """Read DB1 safety status."""
    data = s7client.db_read(1, 0, 22)
    assert len(data) == 22
    # Bit 0 of byte 0 = sis_armed (should be True)
    assert data[0] & 0x01 == 1


def test_read_db2(s7client):
    """Read DB2 setpoints - cl_trip_high should be 500."""
    data = s7client.db_read(2, 0, 16)
    cl_hi = struct.unpack_from('>H', data, 0)[0]
    assert cl_hi == 500


def test_write_db2_setpoint(s7client):
    """Write new cl_trip_high, verify it changes."""
    new_val = 600
    buf = bytearray(2)
    struct.pack_into('>H', buf, 0, new_val)
    s7client.db_write(2, 0, buf)
    time.sleep(0.2)
    data = s7client.db_read(2, 0, 2)
    read_val = struct.unpack_from('>H', data, 0)[0]
    assert read_val == new_val
    # Restore
    struct.pack_into('>H', buf, 0, 500)
    s7client.db_write(2, 0, buf)


def test_maintenance_mode(s7client, sis_server):
    """Set maintenance password + bit, verify maintenance mode."""
    # Write password 7777 to DB2.DBW14
    buf = bytearray(2)
    struct.pack_into('>H', buf, 0, 7777)
    s7client.db_write(2, 14, buf)

    # Set maintenance bit (DB1.DBX0.4)
    db1_byte0 = s7client.db_read(1, 0, 1)
    db1_byte0[0] |= (1 << 4)  # set bit 4
    s7client.db_write(1, 0, db1_byte0)

    time.sleep(0.3)
    assert sis_server.maintenance_mode

    # Clear maintenance bit
    db1_byte0[0] &= ~(1 << 4)
    s7client.db_write(1, 0, db1_byte0)
    time.sleep(0.2)


def test_trip_on_high_chlorine(sis_server):
    """Set simulated chlorine high via DB2 setpoint change, wait for trip."""
    # Lower cl_trip_high to 100 (1.00 ppm) so normal ~1.5 triggers it
    struct.pack_into('>H', sis_server.db2, 0, 100)
    # Set trip delay very short
    struct.pack_into('>H', sis_server.db2, 10, 100)
    time.sleep(1.0)
    assert sis_server.sis_tripped
    # Restore
    sis_server.reset_trip()
    struct.pack_into('>H', sis_server.db2, 0, 500)
    struct.pack_into('>H', sis_server.db2, 10, 2000)
    time.sleep(0.2)


def test_trip_latches(sis_server):
    """After trip, verify it stays tripped."""
    # Trip by lowering setpoint
    struct.pack_into('>H', sis_server.db2, 0, 100)
    struct.pack_into('>H', sis_server.db2, 10, 100)
    time.sleep(1.0)
    assert sis_server.sis_tripped
    # Restore setpoint but trip should latch
    struct.pack_into('>H', sis_server.db2, 0, 500)
    time.sleep(0.3)
    assert sis_server.sis_tripped
    # Clean up
    sis_server.reset_trip()
    struct.pack_into('>H', sis_server.db2, 10, 2000)
    time.sleep(0.2)


def test_hidden_flag(s7client):
    """Read DB99 and verify flag data is present."""
    data = s7client.db_read(99, 0, 20)
    # Decode: 10 big-endian UINTs -> pairs of ASCII chars
    words = struct.unpack('>10H', bytes(data[:20]))
    flag = ''.join(chr(w >> 8) + chr(w & 0xFF) for w in words).rstrip('\x00')
    assert flag.startswith("SYSRUPT{")
    assert "s7_s4f3ty" in flag


def test_redis_state(sis_server):
    """sis:status key should exist in Redis."""
    time.sleep(0.5)
    try:
        import redis
        r = redis.Redis(host="127.0.0.1", port=6379, decode_responses=True,
                        socket_connect_timeout=1)
        r.ping()
        status = r.get("sis:status")
        assert status in ("armed", "tripped", "maintenance")
    except Exception:
        pytest.skip("Redis not available")


def test_redis_trip_event(sis_server):
    """Subscribe to sis.trip, trigger trip, receive event."""
    try:
        import redis
        r = redis.Redis(host="127.0.0.1", port=6379, decode_responses=True,
                        socket_connect_timeout=1)
        r.ping()
    except Exception:
        pytest.skip("Redis not available")

    ps = r.pubsub()
    ps.subscribe("sis.trip")
    # Consume subscribe confirmation
    ps.get_message(timeout=1)

    # Trigger trip
    struct.pack_into('>H', sis_server.db2, 0, 100)
    struct.pack_into('>H', sis_server.db2, 10, 100)
    sis_server.reset_trip()  # ensure clean state
    time.sleep(1.5)

    msg = ps.get_message(timeout=3)
    # Clean up
    sis_server.reset_trip()
    struct.pack_into('>H', sis_server.db2, 0, 500)
    struct.pack_into('>H', sis_server.db2, 10, 2000)

    assert msg is not None
    data = json.loads(msg["data"])
    assert "code" in data
