"""Smoke tests for the RTU sensors BACnet/IP service."""
import asyncio
import os
import socket
import sys
import threading
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
    "rtu_sensors_server", os.path.join(SERVICE, "server.py")
)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


TEST_PORT = 47821
TEST_DEVICE = 110


@pytest.fixture(scope="module")
def server():
    rtu = mod.FieldSensorsBACnet(
        bind_address=f"host:{TEST_PORT}", device_id=TEST_DEVICE
    )
    loop = asyncio.new_event_loop()
    ready = threading.Event()

    async def run():
        rtu.app = rtu._build_app()
        rtu.running = True
        rtu._publish_state()
        asyncio.create_task(rtu._scan_loop())
        ready.set()
        while rtu.running:
            await asyncio.sleep(0.2)

    def target():
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(run())
        except Exception:
            pass

    t = threading.Thread(target=target, daemon=True)
    t.start()
    assert ready.wait(10)
    time.sleep(0.5)
    yield rtu
    rtu.running = False
    try:
        if rtu.app is not None:
            loop.call_soon_threadsafe(rtu.app.close)
    except Exception:
        pass
    time.sleep(0.3)


def test_app_created(server):
    assert server.app is not None
    # AI and BI objects added.
    assert len(server.ais) == 8
    assert len(server.bis) == 4


def test_udp_port_bound(server):
    """Confirm a UDP socket is bound on the BACnet port on some interface."""
    import subprocess
    out = subprocess.run(
        ["ss", "-u", "-l", "-n"], capture_output=True, text=True, timeout=5
    ).stdout
    assert f":{TEST_PORT}" in out, f"no UDP listener on port {TEST_PORT}\n{out}"


def test_redis_state_published(server):
    time.sleep(5.5)
    if server._redis is None:
        pytest.skip("redis unavailable")
    status = server._redis.get("bms:sensors:status")
    assert status == "running"
    full = server._redis.get("bms:sensors:full_state")
    assert full is not None
    import json
    payload = json.loads(full)
    assert payload["protocol"] == "bacnet-ip"
    assert "ambient_temp_c" in payload["analog_inputs"]
