"""Tests for the orchestrator module."""

import json
import pytest
import redis

from orchestrator.main import SERVICES, Orchestrator, run_health_check, ServiceDef
from orchestrator.event_bus import EventChannels, RedisKeys, EventBus
from orchestrator.state import StateManager
from orchestrator.reset import reset_scenario


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def r():
    """Redis client for test assertions."""
    return redis.Redis(host="127.0.0.1", port=6379, decode_responses=True)


@pytest.fixture(autouse=True)
def clean_test_keys(r):
    """Clean up test keys before and after each test."""
    for pattern in ("ctf:*", "ids:*", "physics:*"):
        keys = r.keys(pattern)
        if keys:
            r.delete(*keys)
    yield
    for pattern in ("ctf:*", "ids:*", "physics:*"):
        keys = r.keys(pattern)
        if keys:
            r.delete(*keys)


# ---------------------------------------------------------------------------
# Service definitions
# ---------------------------------------------------------------------------

def test_service_definitions_complete():
    """All services must be defined (24 across 10 phases)."""
    assert len(SERVICES) == 24


def test_phases_ordered():
    """Phases must range from 1 to 10 with no gaps."""
    phases = sorted(set(s.phase for s in SERVICES))
    assert phases == list(range(1, 11))


def test_all_services_have_names():
    """Every service must have a non-empty name."""
    for svc in SERVICES:
        assert svc.name, f"Service in phase {svc.phase} has no name"


def test_all_services_have_commands():
    """Every service must have a non-empty command."""
    for svc in SERVICES:
        assert svc.command, f"Service {svc.name} has no command"


def test_service_types_valid():
    """Service types must be setup, daemon, or systemd."""
    valid = {"setup", "daemon", "systemd"}
    for svc in SERVICES:
        assert svc.svc_type in valid, f"{svc.name} has invalid type {svc.svc_type}"


# ---------------------------------------------------------------------------
# Health checks
# ---------------------------------------------------------------------------

def test_health_check_redis():
    """Redis ping health check should pass (Redis is running)."""
    svc = ServiceDef(
        name="test-redis",
        phase=1,
        svc_type="systemd",
        command="redis-server",
        health_check="redis_ping",
        health_target="127.0.0.1:6379",
    )
    assert run_health_check(svc) is True


def test_health_check_tcp_bad_port():
    """TCP check on an unused port should fail."""
    svc = ServiceDef(
        name="test-tcp",
        phase=1,
        svc_type="daemon",
        command="true",
        health_check="tcp_port",
        health_target="127.0.0.1:59999",
    )
    assert run_health_check(svc) is False


def test_health_check_redis_key_missing():
    """Redis key check should fail when key doesn't exist."""
    svc = ServiceDef(
        name="test-key",
        phase=1,
        svc_type="daemon",
        command="true",
        health_check="redis_key",
        health_target="nonexistent:test:key:12345",
    )
    assert run_health_check(svc) is False


def test_health_check_redis_key_present(r):
    """Redis key check should pass when key exists."""
    r.set("test:health:check:key", "1")
    svc = ServiceDef(
        name="test-key",
        phase=1,
        svc_type="daemon",
        command="true",
        health_check="redis_key",
        health_target="test:health:check:key",
    )
    assert run_health_check(svc) is True
    r.delete("test:health:check:key")


# ---------------------------------------------------------------------------
# Reset
# ---------------------------------------------------------------------------

def test_reset_clears_ctf(r):
    """reset_scenario should clear all ctf:* keys."""
    r.set("ctf:score", "500")
    r.set("ctf:active", "1")
    r.set("ctf:flags_captured", json.dumps(["CH-01"]))
    reset_scenario()
    assert r.get("ctf:score") is None
    assert r.get("ctf:active") is None
    assert r.get("ctf:flags_captured") is None


def test_reset_clears_ids(r):
    """reset_scenario should clear all ids:* keys."""
    r.set("ids:active", "true")
    r.set("ids:alert_count", "10")
    r.set("ids:threat_level", "HIGH")
    reset_scenario()
    assert r.get("ids:active") is None
    assert r.get("ids:alert_count") is None


def test_reset_clears_physics(r):
    """reset_scenario should clear all physics:* keys."""
    r.set("physics:plant_state", json.dumps({"tank_level": 50}))
    r.set("physics:victory", "1")
    reset_scenario()
    assert r.get("physics:plant_state") is None
    assert r.get("physics:victory") is None


# ---------------------------------------------------------------------------
# Event bus
# ---------------------------------------------------------------------------

def test_event_bus_channels_defined():
    """EventChannels should have at least 10 channel constants."""
    attrs = [a for a in dir(EventChannels)
             if not a.startswith("_") and isinstance(getattr(EventChannels, a), str)]
    assert len(attrs) >= 10, f"Only {len(attrs)} channels defined"


def test_event_bus_keys_defined():
    """RedisKeys should have at least 10 key constants."""
    attrs = [a for a in dir(RedisKeys)
             if not a.startswith("_") and isinstance(getattr(RedisKeys, a), str)]
    assert len(attrs) >= 10, f"Only {len(attrs)} keys defined"


# ---------------------------------------------------------------------------
# Status
# ---------------------------------------------------------------------------

def test_status_returns_dict():
    """Orchestrator.status() should return a dict with all service names."""
    orch = Orchestrator()
    result = orch.status()
    assert isinstance(result, dict)
    assert len(result) == 24
    for svc in SERVICES:
        assert svc.name in result


# ---------------------------------------------------------------------------
# State manager
# ---------------------------------------------------------------------------

def test_state_manager_set_get(r):
    """StateManager should set and get values."""
    sm = StateManager()
    sm.set("test:sm:key", {"foo": "bar"})
    val = sm.get("test:sm:key")
    assert val == {"foo": "bar"}
    r.delete("test:sm:key")


def test_state_manager_get_all(r):
    """get_all should return ctf/ids/physics keys."""
    sm = StateManager()
    r.set("ctf:test_ga", "1")
    r.set("ids:test_ga", "2")
    result = sm.get_all()
    assert "ctf:test_ga" in result
    assert "ids:test_ga" in result
    r.delete("ctf:test_ga", "ids:test_ga")
