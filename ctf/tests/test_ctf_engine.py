"""Tests for the CTF auto-detection engine."""

import json
import time

import pytest
import redis

from ctf.engine import CTFEngine, CHALLENGES, TOTAL_POINTS


@pytest.fixture
def r():
    """Raw Redis connection for test assertions."""
    c = redis.Redis(host="127.0.0.1", port=6379, decode_responses=True)
    c.ping()
    # Clean up before test
    for key in c.keys("ctf:*"):
        c.delete(key)
    c.delete("corp:admin_login")
    c.delete("scada:hmi_login")
    c.delete("physics:victory")
    yield c
    # Clean up after test
    for key in c.keys("ctf:*"):
        c.delete(key)
    c.delete("corp:admin_login")
    c.delete("scada:hmi_login")
    c.delete("physics:victory")


@pytest.fixture
def engine(r):
    """Create, start, yield, then stop+reset an engine."""
    e = CTFEngine()
    e.start()
    yield e
    e.stop()
    e.reset()


# -------------------------------------------------------------------
# Basic tests
# -------------------------------------------------------------------

def test_engine_starts(engine):
    assert engine._running is True


def test_initial_state(engine):
    assert engine.score == 0
    assert engine.flags_captured == []


def test_challenge_count(engine):
    assert len(CHALLENGES) == 10


def test_total_points(engine):
    assert TOTAL_POINTS == 4700


# -------------------------------------------------------------------
# Award mechanics
# -------------------------------------------------------------------

def test_award_challenge(engine, r):
    engine.award(1)
    assert "1" in engine.flags_captured
    assert engine.score == 100
    assert r.get("ctf:score") == "100"


def test_no_duplicate_award(engine):
    engine.award(1)
    engine.award(1)
    assert engine.flags_captured.count("1") == 1
    assert engine.score == 100


def test_start_time_set(engine, r):
    engine.award(1)
    assert engine.start_time is not None
    st = r.get("ctf:start_time")
    assert st is not None
    assert float(st) > 0


def test_flag_captured_event(engine, r):
    """Award should publish ctf:flag_captured."""
    ps = r.pubsub()
    ps.subscribe("ctf:flag_captured")
    # Consume subscribe confirmation
    ps.get_message(timeout=1)
    time.sleep(0.2)

    engine.award(1)
    time.sleep(0.5)

    msg = ps.get_message(timeout=2)
    assert msg is not None
    assert msg["type"] == "message"
    data = json.loads(msg["data"])
    assert data["id"] == 1
    assert data["points"] == 100
    ps.unsubscribe()
    ps.close()


# -------------------------------------------------------------------
# Per-challenge trigger tests (pub/sub)
# -------------------------------------------------------------------

def test_ch1_admin_login(engine, r):
    """CH-01: corp:admin_login key exists."""
    r.set("corp:admin_login", json.dumps({"username": "admin"}))
    time.sleep(1.5)
    assert "1" in engine.flags_captured


def test_ch2_opcua_access(engine, r):
    """CH-02: opcua.access with ServiceHistory."""
    r.publish("opcua.access", json.dumps({
        "type": "read",
        "node_path": "PlantInfo/Maintenance/ServiceHistory/Entry_2024_03_15/Notes",
        "client_ip": "10.0.2.50",
    }))
    time.sleep(0.5)
    assert "2" in engine.flags_captured


def test_ch3_scada_login(engine, r):
    """CH-03: scada:hmi_login key exists."""
    r.set("scada:hmi_login", json.dumps({"username": "operator"}))
    time.sleep(1.5)
    assert "3" in engine.flags_captured


def test_ch4_bms_access(engine, r):
    """CH-04: bms.access with object=AV:99."""
    r.publish("bms.access", json.dumps({
        "type": "read",
        "object": "AV:99",
        "property": "presentValue",
        "client_ip": "10.0.1.50",
    }))
    time.sleep(0.5)
    assert "4" in engine.flags_captured


def test_ch5_dnp3(engine, r):
    """CH-05: ot.protocol.write with protocol=dnp3, direct_operate."""
    r.publish("ot.protocol.write", json.dumps({
        "plc_id": "filtration",
        "protocol": "dnp3",
        "operation": "direct_operate",
        "raw": "aabb",
    }))
    time.sleep(0.5)
    assert "5" in engine.flags_captured


def test_ch6_enip(engine, r):
    """CH-06: ot.protocol.write with protocol=enip, class_id=100."""
    r.publish("ot.protocol.write", json.dumps({
        "plc_id": "distribution",
        "protocol": "enip",
        "operation": "set_attribute",
        "class_id": 100,
    }))
    time.sleep(0.5)
    assert "6" in engine.flags_captured


def test_ch7_iec104(engine, r):
    """CH-07: ot.protocol.write with protocol=iec104, ioa=400."""
    r.publish("ot.protocol.write", json.dumps({
        "plc_id": "power",
        "protocol": "iec104",
        "operation": "command",
        "ioa": 400,
    }))
    time.sleep(0.5)
    assert "7" in engine.flags_captured


def test_ch7_iec104_alt_protocol_name(engine, r):
    """CH-07 also works with iec-60870-5-104 protocol name."""
    r.publish("ot.protocol.write", json.dumps({
        "plc_id": "power",
        "protocol": "iec-60870-5-104",
        "operation": "main_breaker",
        "ioa": 400,
    }))
    time.sleep(0.5)
    assert "7" in engine.flags_captured


def test_ch8_both_conditions(engine, r):
    """CH-08: modbus.write with BOTH addr=9,val=0 AND addr=10,val>50."""
    r.publish("modbus.write", json.dumps({
        "plc_id": "chemical",
        "address": 9,
        "values": [0],
    }))
    time.sleep(0.3)
    r.publish("modbus.write", json.dumps({
        "plc_id": "chemical",
        "address": 10,
        "values": [75],
    }))
    time.sleep(0.5)
    assert "8" in engine.flags_captured


def test_ch8_single_condition_not_enough(engine, r):
    """CH-08: only one condition is NOT enough."""
    r.publish("modbus.write", json.dumps({
        "plc_id": "chemical",
        "address": 9,
        "values": [0],
    }))
    time.sleep(0.5)
    assert "8" not in engine.flags_captured


def test_ch9_sis_maintenance(engine, r):
    """CH-09: sis.maintenance with enabled=true."""
    r.publish("sis.maintenance", json.dumps({
        "enabled": True,
        "timestamp": time.time(),
    }))
    time.sleep(0.5)
    assert "9" in engine.flags_captured


def test_ch9_sis_write(engine, r):
    """CH-09 alt: sis.write with db=2, offset=0, value>800."""
    r.publish("sis.write", json.dumps({
        "db": 2,
        "offset": 0,
        "value": 900,
    }))
    time.sleep(0.5)
    assert "9" in engine.flags_captured


def test_ch10_victory(engine, r):
    """CH-10: physics:victory key exists."""
    r.set("physics:victory", json.dumps({"msg": "plant compromised"}))
    time.sleep(1.5)
    assert "10" in engine.flags_captured


# -------------------------------------------------------------------
# Reset
# -------------------------------------------------------------------

def test_reset(engine, r):
    engine.award(1)
    engine.award(2)
    assert engine.score == 300
    engine.reset()
    assert engine.score == 0
    assert engine.flags_captured == []
    assert r.get("ctf:score") is None


# -------------------------------------------------------------------
# Restart survival
# -------------------------------------------------------------------

def test_survives_restart(r):
    """State persists across engine instances."""
    e1 = CTFEngine()
    e1.start()
    e1.award(1)
    e1.award(3)
    assert e1.score == 400
    e1.stop()

    e2 = CTFEngine()
    assert e2.score == 400
    assert "1" in e2.flags_captured
    assert "3" in e2.flags_captured
    e2.reset()


# -------------------------------------------------------------------
# Hint timer
# -------------------------------------------------------------------

def test_hint_timer(r):
    """If start_time was 16 min ago, hint_level should be 1."""
    e = CTFEngine()
    e._start_time = time.time() - 16 * 60  # 16 min ago
    r.set("ctf:start_time", str(e._start_time))
    e.start()
    time.sleep(6)  # wait for hint timer to run
    raw = r.get("ctf:hint_state")
    assert raw is not None
    hint = json.loads(raw)
    assert hint["hint_level"] >= 1
    e.stop()
    e.reset()
