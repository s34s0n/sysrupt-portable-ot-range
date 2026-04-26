"""Tests for the display game hub - state machine, server, and Redis reader."""

import pytest
import time
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from display.server import app, socketio, DisplayStateMachine, RedisStateReader, CHALLENGES, TOTAL_POINTS


@pytest.fixture
def client():
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c


@pytest.fixture
def sm():
    return DisplayStateMachine()


# --- Server tests ---

def test_server_starts(client):
    r = client.get("/")
    assert r.status_code == 200


def test_homepage_contains_sysrupt(client):
    r = client.get("/")
    assert b"SYSRUPT" in r.data


def test_homepage_contains_screens(client):
    r = client.get("/")
    data = r.data.decode()
    for screen_id in ["boot", "idle", "progress", "hint", "plant_mini",
                      "flag_captured", "attack_alert", "sis_trip", "victory"]:
        assert f'id="screen-{screen_id}"' in data, f"Missing screen: {screen_id}"


# --- Challenge data tests ---

def test_challenge_data_correct():
    assert len(CHALLENGES) == 10
    assert TOTAL_POINTS == 4700
    assert CHALLENGES[0]["points"] == 100
    assert CHALLENGES[9]["points"] == 1000


def test_challenge_ids_sequential():
    for i, ch in enumerate(CHALLENGES):
        assert ch["id"] == i + 1


def test_challenge_points_ascending():
    for i in range(len(CHALLENGES) - 1):
        assert CHALLENGES[i]["points"] <= CHALLENGES[i + 1]["points"]


# --- State machine tests ---

def test_state_machine_boot(sm):
    state = sm.update({"score": 0, "flags_captured": []})
    assert state == "boot"


def test_state_machine_boot_to_idle(sm):
    sm.boot_time = time.time() - 6
    # First call transitions internally but still returns boot
    sm.update({"score": 0, "flags_captured": []})
    # Second call sees IDLE state
    state = sm.update({"score": 0, "flags_captured": []})
    assert state == "idle"


def test_state_machine_idle_to_active(sm):
    sm.state = sm.IDLE
    state = sm.update({"score": 100, "flags_captured": ["1"], "start_time": str(time.time())})
    assert state in [sm.ACTIVE_PROGRESS, sm.FLAG_CAPTURED]


def test_state_machine_flag_interrupt(sm):
    sm.state = sm.ACTIVE_PROGRESS
    sm.prev_flags = set()
    state = sm.update({"score": 100, "flags_captured": ["1"]})
    assert state == sm.FLAG_CAPTURED


def test_state_machine_attack_interrupt(sm):
    sm.state = sm.ACTIVE_PROGRESS
    sm.rotation_timer = time.time()
    state = sm.update({
        "score": 0, "flags_captured": [],
        "start_time": str(time.time()),
        "attack_status": {"chlorine_danger": True},
    })
    assert state == sm.ATTACK_ALERT


def test_state_machine_sis_trip(sm):
    sm.state = sm.ACTIVE_PROGRESS
    state = sm.update({"score": 0, "flags_captured": [], "sis_tripped": True})
    assert state == sm.SIS_TRIP


def test_state_machine_victory_permanent(sm):
    sm.state = sm.ACTIVE_PROGRESS
    state = sm.update({
        "score": 4700,
        "flags_captured": ["1", "2", "3", "4", "5", "6", "7", "8", "9", "10"],
        "victory": {"chlorine_ppm": 8.5},
    })
    assert state == sm.VICTORY
    # Should stay victory even with empty state
    state2 = sm.update({"score": 0, "flags_captured": []})
    assert state2 == sm.VICTORY


def test_screen_rotation(sm):
    sm.state = sm.ACTIVE_PROGRESS
    sm.rotation_index = 0
    sm.rotation_timer = time.time() - 11  # past 10s progress time
    state = sm.update({"score": 100, "flags_captured": ["1"], "start_time": str(time.time())})
    # Either rotated to hint or got flag interrupt
    assert state in [sm.ACTIVE_HINT, sm.FLAG_CAPTURED]


def test_socketio_connects(client):
    sio_client = socketio.test_client(app, flask_test_client=client)
    assert sio_client.is_connected()
    sio_client.disconnect()


# --- Redis reader tests ---

def test_redis_state_reader_defaults():
    """Test RedisStateReader defaults when Redis is unavailable."""
    reader = RedisStateReader()
    state = reader.read()
    assert "score" in state
    assert "flags_captured" in state
    assert isinstance(state["chlorine_ppm"], (int, float))
    assert isinstance(state["flags_captured"], list)


def test_redis_state_reader_plant_defaults():
    reader = RedisStateReader()
    defaults = reader._plant_defaults()
    assert defaults["chlorine_ppm"] == 1.5
    assert defaults["ph"] == 7.2
    assert defaults["voltage"] == 230
    assert defaults["sis_tripped"] is False
