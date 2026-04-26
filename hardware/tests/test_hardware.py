"""Comprehensive pytest suite for the hardware abstraction layer."""
from __future__ import annotations

import json
import time

import pytest

from hardware.manager import HardwareManager


def _redis_available() -> bool:
    try:
        import redis
        c = redis.Redis(host="127.0.0.1", port=6379, db=0, socket_connect_timeout=1)
        return c.ping()
    except Exception:
        return False


REDIS_OK = _redis_available()


@pytest.fixture
def manager():
    """Create a HardwareManager, yield it, ensure stop() in teardown."""
    hw = HardwareManager()
    hw.start()
    yield hw
    hw.stop()


@pytest.fixture
def redis_client():
    """Connect to Redis for verification."""
    if not REDIS_OK:
        pytest.skip("Redis not available")
    import redis
    return redis.Redis(host="127.0.0.1", port=6379, db=0, decode_responses=True)


# ------------------- Temperature -------------------

def test_temperature_returns_float(manager):
    value = manager.get_temperature("temp_process")
    assert isinstance(value, float)


def test_temperature_in_range(manager):
    for _ in range(20):
        v = manager.get_temperature("temp_process")
        assert 15.0 <= v <= 45.0
    for _ in range(20):
        v = manager.get_temperature("temp_ambient")
        assert 20.0 <= v <= 55.0


def test_temperature_has_noise(manager):
    readings = []
    for _ in range(10):
        readings.append(manager.get_temperature("temp_process"))
        time.sleep(0.001)
    assert len(set(readings)) > 1, "Expected noise - not all readings identical"


def test_temperature_override(manager):
    manager.set_temperature_override("temp_process", 99.0)
    # override is clamped to max_c = 45.0
    v = manager.get_temperature("temp_process")
    assert 44.0 <= v <= 45.0
    manager.set_temperature_override("temp_process", 25.0)
    v = manager.get_temperature("temp_process")
    assert 24.0 <= v <= 26.0


def test_temperature_clear_override(manager):
    manager.set_temperature_override("temp_process", 25.0)
    manager.set_temperature_override("temp_process", None)
    assert manager.sensors["temp_process"].override is None


def test_get_all_temperatures(manager):
    temps = manager.get_all_temperatures()
    assert "temp_process" in temps
    assert "temp_ambient" in temps
    assert all(isinstance(v, float) for v in temps.values())


# ------------------- Relay -------------------

def test_relay_initial_state(manager):
    for rid in ("relay1", "relay2", "relay3", "relay4"):
        assert manager.get_relay(rid) is False


def test_relay_set_on(manager):
    manager.set_relay("relay1", True)
    assert manager.get_relay("relay1") is True


def test_relay_set_off(manager):
    manager.set_relay("relay1", True)
    time.sleep(0.15)
    manager.set_relay("relay1", False)
    assert manager.get_relay("relay1") is False


def test_relay_toggle(manager):
    manager.set_relay("relay2", True)
    assert manager.get_relay("relay2") is True
    time.sleep(0.15)
    manager.set_relay("relay2", False)
    assert manager.get_relay("relay2") is False


def test_relay_cycle_count(manager):
    relay = manager.relays["relay3"]
    assert relay.total_cycles == 0
    manager.set_relay("relay3", True)
    time.sleep(0.15)
    manager.set_relay("relay3", False)
    time.sleep(0.15)
    manager.set_relay("relay3", True)
    assert relay.total_cycles == 3


def test_relay_debounce(manager):
    relay = manager.relays["relay4"]
    manager.set_relay("relay4", True)
    cycles_after_first = relay.total_cycles
    # Immediately toggle back within debounce window
    manager.set_relay("relay4", False)
    # debounce should have blocked it - state should remain True
    assert relay.total_cycles == cycles_after_first
    assert relay.get_state() is True


def test_get_all_relays(manager):
    relays = manager.get_all_relays()
    assert set(relays.keys()) == {"relay1", "relay2", "relay3", "relay4"}


# ------------------- LED -------------------

def test_led_initial_state(manager):
    for lid in ("led_zone_it", "led_zone_dmz", "led_zone_ot", "led_zone_safety"):
        assert manager.get_led(lid) == "off"


def test_led_set_on(manager):
    manager.set_led("led_zone_it", "on")
    assert manager.get_led("led_zone_it") == "on"


def test_led_set_blink(manager):
    manager.set_led("led_zone_dmz", "blink")
    assert manager.get_led("led_zone_dmz") == "blink"


def test_led_invalid_state(manager):
    with pytest.raises(ValueError):
        manager.set_led("led_zone_ot", "sparkle")


def test_get_all_leds(manager):
    leds = manager.get_all_leds()
    assert set(leds.keys()) == {
        "led_zone_it", "led_zone_dmz", "led_zone_ot", "led_zone_safety"
    }


# ------------------- Redis -------------------

@pytest.mark.skipif(not REDIS_OK, reason="Redis not available")
def test_redis_state_published(manager, redis_client):
    time.sleep(0.75)  # 1.5 * update_interval (500ms)
    raw = redis_client.get("hw:full_state")
    assert raw is not None
    data = json.loads(raw)
    assert data["mode"] == "simulated"
    assert "temperatures" in data


@pytest.mark.skipif(not REDIS_OK, reason="Redis not available")
def test_redis_relay_event(manager, redis_client):
    import redis as redis_module
    events: list = []
    pubsub = redis_client.pubsub()
    pubsub.subscribe("hardware.relay.change")
    # consume subscribe ack
    time.sleep(0.1)
    pubsub.get_message(timeout=0.5)

    manager.set_relay("relay1", True)

    deadline = time.time() + 2.0
    while time.time() < deadline:
        msg = pubsub.get_message(timeout=0.2)
        if msg and msg.get("type") == "message":
            events.append(json.loads(msg["data"]))
            break
    pubsub.close()
    assert len(events) >= 1
    assert events[0]["relay_id"] == "relay1"
    assert events[0]["state"] is True


@pytest.mark.skipif(not REDIS_OK, reason="Redis not available")
def test_redis_full_state_valid_json(manager, redis_client):
    time.sleep(0.75)
    raw = redis_client.get("hw:full_state")
    assert raw is not None
    data = json.loads(raw)
    assert isinstance(data, dict)
    assert "relays" in data
    assert "leds" in data


# ------------------- Manager -------------------

def test_manager_start_stop():
    hw = HardwareManager()
    hw.start()
    time.sleep(0.2)
    assert hw._thread is not None
    hw.stop()
    assert hw._thread is None


def test_manager_get_full_state(manager):
    state = manager.get_full_state()
    assert "mode" in state
    assert "timestamp" in state
    assert "temperatures" in state
    assert "relays" in state
    assert "leds" in state
    assert "uptime_seconds" in state
    assert state["mode"] == "simulated"


def test_manager_reset(manager):
    manager.set_relay("relay1", True)
    time.sleep(0.15)
    manager.set_led("led_zone_it", "on")
    manager.set_temperature_override("temp_process", 40.0)
    manager.reset()
    assert manager.get_relay("relay1") is False
    assert manager.get_led("led_zone_it") == "off"
    assert manager.sensors["temp_process"].override is None


def test_manager_simulated_mode(manager):
    assert manager.mode == "simulated"
