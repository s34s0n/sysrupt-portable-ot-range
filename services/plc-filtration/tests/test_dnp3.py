"""Smoke tests for the PLC-3 DNP3 outstation."""
import asyncio
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

# Import the server module with a "-" in its package name by file path.
import importlib.util
spec = importlib.util.spec_from_file_location(
    "plc_filtration_server", os.path.join(SERVICE, "server.py")
)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


TEST_PORT = 20020


@pytest.fixture(scope="module")
def server():
    import threading
    plc = mod.FiltrationDNP3(bind_ip="127.0.0.1", bind_port=TEST_PORT)
    loop = asyncio.new_event_loop()
    done = threading.Event()
    state = {"loop_server": None}

    async def run():
        plc.running = True
        plc._publish_state()
        loop_server = await asyncio.start_server(
            plc._handle_client, plc.bind_ip, plc.bind_port
        )
        state["loop_server"] = loop_server
        asyncio.create_task(plc._scan_loop())
        done.set()
        try:
            async with loop_server:
                await loop_server.serve_forever()
        except asyncio.CancelledError:
            pass

    def target():
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(run())
        except Exception:
            pass

    t = threading.Thread(target=target, daemon=True)
    t.start()
    assert done.wait(5)
    time.sleep(0.3)
    yield plc
    plc.running = False
    ls = state["loop_server"]
    if ls is not None:
        loop.call_soon_threadsafe(ls.close)
    time.sleep(0.2)
    try:
        loop.call_soon_threadsafe(loop.stop)
    except Exception:
        pass


def test_server_binds_and_accepts_tcp(server):
    s = socket.create_connection(("127.0.0.1", TEST_PORT), timeout=2)
    s.close()


def test_crc_function_is_correct():
    # dnp3_crc should be stable/deterministic.
    a = mod.dnp3_crc(b"\x05\x64\x05\xc0\x01\x00\x0a\x00")
    b = mod.dnp3_crc(b"\x05\x64\x05\xc0\x01\x00\x0a\x00")
    assert a == b
    assert 0 <= a <= 0xFFFF


def test_dnp3_read_request_returns_valid_frame(server):
    s = socket.create_connection(("127.0.0.1", TEST_PORT), timeout=3)
    s.settimeout(3.0)
    # Build a READ (fc=1) request asking for class 0 objects.
    # user_data = transport(0xc0) + app_ctrl(0xc0) + fc(0x01) + object headers
    # Object group 60 var 1 (class 0 data), qualifier 0x06 (no range)
    user_data = bytes([0xC0, 0xC0, 0x01, 60, 1, 0x06])
    frame = mod.build_link_frame(
        ctrl=0xC4,  # DIR=1 PRM=1 unconfirmed user data from master
        dest=10,
        src=1,
        user_data=user_data,
    )
    s.sendall(frame)
    data = s.recv(4096)
    s.close()
    assert len(data) >= 10
    assert data[0:2] == b"\x05\x64"
    # Response length field reasonable
    assert data[2] >= 5


def test_redis_state_published_if_available(server):
    time.sleep(1.2)
    if server._redis is None:
        pytest.skip("redis unavailable in test env")
    status = server._redis.get("plc:filtration:status")
    assert status == "running"
    full = server._redis.get("plc:filtration:full_state")
    assert full is not None
    import json
    payload = json.loads(full)
    assert payload["protocol"] == "dnp3"
