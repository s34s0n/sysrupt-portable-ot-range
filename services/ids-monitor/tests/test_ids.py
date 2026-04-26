"""Tests for the IDS engine -- 25+ tests covering all rule categories."""

import json
import sys
import os
import time

import pytest
import redis

# Add ids-monitor dir to path so we can import engine
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from engine import IDSEngine, IDSRule, AlertSeverity, _build_rules


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def r():
    """Raw Redis connection."""
    c = redis.Redis(host="127.0.0.1", port=6379, decode_responses=True)
    c.ping()
    for key in c.keys("ids:*"):
        c.delete(key)
    yield c
    for key in c.keys("ids:*"):
        c.delete(key)


@pytest.fixture
def engine(r):
    """Start an IDS engine, yield, stop+reset."""
    e = IDSEngine()
    e.start()
    time.sleep(0.3)  # let threads start
    yield e
    e.stop()
    e.reset()


# ---------------------------------------------------------------------------
# Engine basics
# ---------------------------------------------------------------------------

def test_engine_starts(engine):
    assert engine._running is True


def test_rules_loaded(engine):
    assert len(engine.rules) >= 22


def test_initial_state(engine):
    assert engine.alert_count == 0
    assert engine.threat_level == "NONE"


def test_initial_alerts_empty(engine):
    assert engine.alerts == []


# ---------------------------------------------------------------------------
# Individual rule triggers -- via direct fire_rule
# ---------------------------------------------------------------------------

def test_fire_ids010_unauthorized_modbus(engine):
    engine.fire_rule("IDS-010", "10.0.99.1", {"plc_id": "chemical"})
    assert engine.alert_count == 1
    assert engine.alerts[0]["rule_id"] == "IDS-010"
    assert engine.alerts[0]["severity"] == "MEDIUM"


def test_fire_ids020_pid_manual(engine):
    engine.fire_rule("IDS-020", "10.0.1.52")
    assert engine.alert_count == 1
    assert engine.alerts[0]["severity"] == "HIGH"


def test_fire_ids022_alarm_inhibit(engine):
    engine.fire_rule("IDS-022", "10.0.1.52")
    assert engine.alert_count == 1
    assert engine.alerts[0]["severity"] == "CRITICAL"


def test_fire_ids030_sis_maintenance(engine):
    engine.fire_rule("IDS-030", "10.0.1.52")
    assert engine.alert_count == 1
    assert engine.alerts[0]["severity"] == "CRITICAL"


def test_fire_ids011_s7comm(engine):
    engine.fire_rule("IDS-011", "10.0.1.52")
    assert engine.alert_count == 1
    assert engine.alerts[0]["severity"] == "HIGH"


def test_fire_ids012_dnp3(engine):
    engine.fire_rule("IDS-012", "10.0.1.52")
    assert engine.alert_count == 1
    assert engine.alerts[0]["severity"] == "MEDIUM"


def test_fire_ids014_iec104(engine):
    engine.fire_rule("IDS-014", "10.0.1.52")
    assert engine.alert_count == 1
    assert engine.alerts[0]["severity"] == "HIGH"


def test_fire_ids050_breaker(engine):
    engine.fire_rule("IDS-050", "10.0.1.52")
    assert engine.alert_count == 1
    assert engine.alerts[0]["severity"] == "CRITICAL"


def test_fire_ids002_opcua_enum(engine):
    engine.fire_rule("IDS-002", "10.0.1.52")
    assert engine.alert_count == 1
    assert engine.alerts[0]["severity"] == "LOW"


def test_fire_ids003_bacnet(engine):
    engine.fire_rule("IDS-003", "10.0.1.52")
    assert engine.alert_count == 1
    assert engine.alerts[0]["severity"] == "LOW"


def test_fire_ids031_sis_threshold(engine):
    engine.fire_rule("IDS-031", "10.0.1.52", {"db": 2, "offset": 0, "value": 900})
    assert engine.alert_count == 1
    assert engine.alerts[0]["severity"] == "CRITICAL"


def test_fire_ids040_plc_upload(engine):
    engine.fire_rule("IDS-040", "10.0.1.52")
    assert engine.alert_count == 1
    assert engine.alerts[0]["severity"] == "CRITICAL"


# ---------------------------------------------------------------------------
# Cooldown tests
# ---------------------------------------------------------------------------

def test_cooldown_blocks_rapid_fire(engine):
    """IDS-010 has 30s cooldown -- firing twice quickly should only count once."""
    engine.fire_rule("IDS-010", "10.0.99.1")
    engine.fire_rule("IDS-010", "10.0.99.1")
    assert engine.alert_count == 1


def test_cooldown_allows_after_expiry(engine):
    """After cooldown expires, rule fires again."""
    rule = engine.rules["IDS-010"]
    engine.fire_rule("IDS-010", "10.0.99.1")
    assert engine.alert_count == 1
    # Manually expire cooldown
    rule.last_triggered = time.time() - 31
    engine.fire_rule("IDS-010", "10.0.99.1")
    assert engine.alert_count == 2


def test_zero_cooldown_always_fires(engine):
    """IDS-022 (CRITICAL, cooldown=0) fires every time."""
    engine.fire_rule("IDS-022", "10.0.1.52")
    engine.fire_rule("IDS-022", "10.0.1.52")
    engine.fire_rule("IDS-022", "10.0.1.52")
    assert engine.alert_count == 3


# ---------------------------------------------------------------------------
# Threat level calculation
# ---------------------------------------------------------------------------

def test_threat_none(engine):
    assert engine.threat_level == "NONE"


def test_threat_low(engine):
    engine.fire_rule("IDS-002", "10.0.1.52")  # LOW
    assert engine.threat_level == "LOW"


def test_threat_medium_from_medium_alert(engine):
    engine.fire_rule("IDS-010", "10.0.99.1")  # MEDIUM
    assert engine.threat_level == "MEDIUM"


def test_threat_high_from_high_alert(engine):
    engine.fire_rule("IDS-020", "10.0.1.52")  # HIGH
    assert engine.threat_level == "HIGH"


def test_threat_critical_from_critical_alert(engine):
    engine.fire_rule("IDS-022", "10.0.1.52")  # CRITICAL
    assert engine.threat_level == "CRITICAL"


# ---------------------------------------------------------------------------
# Redis state publication
# ---------------------------------------------------------------------------

def test_redis_alert_count(engine, r):
    engine.fire_rule("IDS-022", "10.0.1.52")
    time.sleep(0.1)
    count = r.get("ids:alert_count")
    assert count == "1"


def test_redis_threat_level(engine, r):
    engine.fire_rule("IDS-022", "10.0.1.52")
    time.sleep(0.1)
    level = r.get("ids:threat_level")
    assert level == "CRITICAL"


def test_redis_alerts_json(engine, r):
    engine.fire_rule("IDS-010", "10.0.99.1")
    time.sleep(0.1)
    raw = r.get("ids:alerts")
    alerts = json.loads(raw)
    assert len(alerts) == 1
    assert alerts[0]["rule_id"] == "IDS-010"


def test_redis_latest_alert(engine, r):
    engine.fire_rule("IDS-020", "10.0.1.52")
    time.sleep(0.1)
    raw = r.get("ids:latest_alert")
    alert = json.loads(raw)
    assert alert["rule_id"] == "IDS-020"


# ---------------------------------------------------------------------------
# Pub/sub alert event
# ---------------------------------------------------------------------------

def test_pubsub_alert_event(engine, r):
    """Subscribe to ids:alert channel and verify alert is received."""
    ps = r.pubsub()
    ps.subscribe("ids:alert")
    # Consume subscribe confirmation
    ps.get_message(timeout=1)
    time.sleep(0.2)

    engine.fire_rule("IDS-022", "10.0.1.52")
    time.sleep(0.5)

    msg = ps.get_message(timeout=2)
    assert msg is not None
    assert msg["type"] == "message"
    data = json.loads(msg["data"])
    assert data["rule_id"] == "IDS-022"

    ps.unsubscribe()
    ps.close()


# ---------------------------------------------------------------------------
# Reset
# ---------------------------------------------------------------------------

def test_reset_clears_state(engine, r):
    engine.fire_rule("IDS-022", "10.0.1.52")
    assert engine.alert_count == 1
    engine.reset()
    assert engine.alert_count == 0
    assert engine.alerts == []
    # Redis keys should be cleared
    assert r.get("ids:alert_count") is None


# ---------------------------------------------------------------------------
# Pub/sub event processing via Redis publish
# ---------------------------------------------------------------------------

def test_modbus_allowed_source_no_alert(engine, r):
    """Modbus write from allowed source should NOT trigger IDS-010."""
    r.publish("modbus.write", json.dumps({
        "plc_id": "chemical", "source_ip": "10.0.4.10",
        "address": 5, "values": [100],
    }))
    time.sleep(0.5)
    assert engine.alert_count == 0


def test_modbus_unauthorized_source_alert(engine, r):
    """Modbus write from unauthorized source triggers IDS-010."""
    r.publish("modbus.write", json.dumps({
        "plc_id": "chemical", "source_ip": "10.0.1.52",
        "address": 5, "values": [100],
    }))
    time.sleep(0.5)
    assert engine.alert_count >= 1
    rule_ids = [a["rule_id"] for a in engine.alerts]
    assert "IDS-010" in rule_ids


def test_modbus_alarm_inhibit_event(engine, r):
    """Modbus write addr=15 val=1 triggers IDS-022."""
    r.publish("modbus.write", json.dumps({
        "plc_id": "chemical", "source_ip": "10.0.1.52",
        "address": 15, "values": [1],
    }))
    time.sleep(0.5)
    rule_ids = [a["rule_id"] for a in engine.alerts]
    assert "IDS-022" in rule_ids


def test_sis_maintenance_event(engine, r):
    """sis.maintenance with enabled=true triggers IDS-030."""
    r.publish("sis.maintenance", json.dumps({
        "enabled": True, "source_ip": "10.0.1.52",
    }))
    time.sleep(0.5)
    rule_ids = [a["rule_id"] for a in engine.alerts]
    assert "IDS-030" in rule_ids


def test_sis_write_triggers_ids011(engine, r):
    """Any sis.write triggers IDS-011."""
    r.publish("sis.write", json.dumps({
        "db": 1, "offset": 0, "value": 100, "source_ip": "10.0.1.52",
    }))
    time.sleep(0.5)
    rule_ids = [a["rule_id"] for a in engine.alerts]
    assert "IDS-011" in rule_ids


def test_dnp3_event(engine, r):
    """DNP3 direct_operate triggers IDS-012."""
    r.publish("ot.protocol.write", json.dumps({
        "protocol": "dnp3", "operation": "direct_operate",
        "source_ip": "10.0.1.52",
    }))
    time.sleep(0.5)
    rule_ids = [a["rule_id"] for a in engine.alerts]
    assert "IDS-012" in rule_ids


def test_iec104_event(engine, r):
    """IEC104 command triggers IDS-014."""
    r.publish("ot.protocol.write", json.dumps({
        "protocol": "iec104", "ioa": 100, "value": 1,
        "source_ip": "10.0.1.52",
    }))
    time.sleep(0.5)
    rule_ids = [a["rule_id"] for a in engine.alerts]
    assert "IDS-014" in rule_ids


def test_opcua_browse_event(engine, r):
    """OPC-UA browse triggers IDS-002."""
    r.publish("opcua.access", json.dumps({
        "operation": "browse", "node_path": "/Objects",
        "source_ip": "10.0.1.52",
    }))
    time.sleep(0.5)
    rule_ids = [a["rule_id"] for a in engine.alerts]
    assert "IDS-002" in rule_ids


def test_bacnet_whois_event(engine, r):
    """BACnet WhoIs triggers IDS-003."""
    r.publish("bms.access", json.dumps({
        "operation": "whois", "source_ip": "10.0.1.52",
    }))
    time.sleep(0.5)
    rule_ids = [a["rule_id"] for a in engine.alerts]
    assert "IDS-003" in rule_ids


def test_chlorine_escalation(engine):
    """Chlorine levels escalate through severity tiers."""
    engine.fire_rule("IDS-025-M", "", {"chlorine_ppm": 2.5})
    assert engine.alerts[-1]["severity"] == "MEDIUM"

    engine.fire_rule("IDS-025-H", "", {"chlorine_ppm": 4.5})
    assert engine.alerts[-1]["severity"] == "HIGH"

    engine.fire_rule("IDS-025-C", "", {"chlorine_ppm": 7.0})
    assert engine.alerts[-1]["severity"] == "CRITICAL"
    assert engine.alert_count == 3


# ---------------------------------------------------------------------------
# Alert format validation
# ---------------------------------------------------------------------------

def test_alert_format(engine):
    """Alert contains all required fields."""
    engine.fire_rule("IDS-022", "10.0.1.52", {"address": 15, "value": 1})
    alert = engine.alerts[0]
    required = ["rule_id", "name", "severity", "description",
                "source_ip", "details", "timestamp", "trigger_count"]
    for field in required:
        assert field in alert, f"Missing field: {field}"


# ---------------------------------------------------------------------------
# IDSRule unit tests
# ---------------------------------------------------------------------------

def test_rule_can_trigger_fresh():
    rule = IDSRule("TEST", "Test", "LOW", "test", cooldown=30)
    assert rule.can_trigger() is True


def test_rule_can_trigger_within_cooldown():
    rule = IDSRule("TEST", "Test", "LOW", "test", cooldown=30)
    rule.mark_triggered()
    assert rule.can_trigger() is False


def test_rule_can_trigger_after_cooldown():
    rule = IDSRule("TEST", "Test", "LOW", "test", cooldown=1)
    rule.mark_triggered()
    time.sleep(1.1)
    assert rule.can_trigger() is True


def test_rule_zero_cooldown():
    rule = IDSRule("TEST", "Test", "CRITICAL", "test", cooldown=0)
    rule.mark_triggered()
    assert rule.can_trigger() is True


# ---------------------------------------------------------------------------
# AlertSeverity
# ---------------------------------------------------------------------------

def test_severity_rank():
    assert AlertSeverity.rank("LOW") < AlertSeverity.rank("MEDIUM")
    assert AlertSeverity.rank("MEDIUM") < AlertSeverity.rank("HIGH")
    assert AlertSeverity.rank("HIGH") < AlertSeverity.rank("CRITICAL")
