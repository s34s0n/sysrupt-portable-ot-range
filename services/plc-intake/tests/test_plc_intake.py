"""
Tests for PLC-1 Intake. Runs on 127.0.0.1:15020 to avoid root/namespace.
"""

import os
import sys
import time

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(_HERE)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from pymodbus.client import ModbusTcpClient  # noqa: E402

from services.plc_common.web_ide import PLCWebIDE  # noqa: E402
from services.plc_intake_server_import import IntakePLC  # noqa: E402

_PORT_COUNTER = [15020]
WEB_PORT_COUNTER = [18080]


def _next_modbus_port():
    _PORT_COUNTER[0] += 1
    return _PORT_COUNTER[0]


def _next_web_port():
    WEB_PORT_COUNTER[0] += 1
    return WEB_PORT_COUNTER[0]


@pytest.fixture
def plc():
    port = _next_modbus_port()

    class TestPLC(IntakePLC):
        BIND_IP = "127.0.0.1"
        BIND_PORT = port

    p = TestPLC()
    p._test_port = port
    p.start()
    time.sleep(0.6)
    yield p
    p.stop()
    time.sleep(0.2)


@pytest.fixture
def plc_with_web(plc):
    wport = _next_web_port()
    web = PLCWebIDE(plc, plc.ST_FILE_PATH, "127.0.0.1", wport)
    web.run()
    time.sleep(0.3)
    plc._web_port = wport
    yield plc, web
    web.stop()


def _client(plc):
    c = ModbusTcpClient("127.0.0.1", port=plc._test_port, timeout=2)
    assert c.connect(), "failed to connect to test PLC"
    return c


def test_plc_starts(plc):
    assert plc.status == "running"
    assert plc.scan_count > 0


def test_modbus_read_holding(plc):
    c = _client(plc)
    try:
        rr = c.read_holding_registers(address=0, count=10)
        assert not rr.isError()
        assert list(rr.registers) == [30, 80, 15, 90, 1, 1, 1, 0, 0, 0]
    finally:
        c.close()


def test_modbus_read_input(plc):
    c = _client(plc)
    try:
        rr = c.read_input_registers(address=0, count=2)
        assert not rr.isError()
        assert list(rr.registers) == [60, 125]
    finally:
        c.close()


def test_modbus_write_coil(plc):
    # Switch to manual mode first so scan cycle does not override
    c = _client(plc)
    try:
        c.write_register(address=4, value=0)  # MANUAL
        time.sleep(0.2)
        c.write_coil(address=0, value=True)
        time.sleep(0.2)
        rr = c.read_coils(address=0, count=1)
        assert not rr.isError()
        assert rr.bits[0] is True
    finally:
        c.close()


def test_modbus_write_holding(plc):
    c = _client(plc)
    try:
        c.write_register(address=0, value=50)
        time.sleep(0.2)
        assert plc.get_holding(0) == 50
    finally:
        c.close()


def test_pump_logic_auto(plc):
    plc.set_input(0, 20)  # low tank level
    time.sleep(0.25)
    assert plc.get_coil(0) is True


def test_pump_logic_stop(plc):
    plc.set_input(0, 85)  # above stop setpoint but below safety
    time.sleep(0.25)
    assert plc.get_coil(0) is False
    assert plc.get_coil(1) is False


def test_high_level_safety(plc):
    plc.set_input(0, 96)  # high-high safety trip
    time.sleep(0.25)
    assert plc.get_coil(0) is False
    assert plc.get_coil(1) is False
    assert plc.get_coil(2) is False  # inlet valve closed


def test_alarm_low(plc):
    plc.set_input(0, 10)
    time.sleep(0.25)
    assert plc.get_coil(4) is True


def test_alarm_high(plc):
    plc.set_input(0, 92)  # above high alarm but below safety
    time.sleep(0.25)
    assert plc.get_coil(5) is True


def test_redis_state_published(plc):
    if plc._redis is None:
        pytest.skip("redis unavailable")
    time.sleep(0.8)
    assert plc._redis.get("plc:intake:status") == "running"
    assert plc._redis.get("plc:intake:full_state") is not None


def test_web_ide_status(plc_with_web):
    import requests

    plc, _web = plc_with_web
    r = requests.get(
        f"http://127.0.0.1:{plc._web_port}/",
        auth=("openplc", "openplc"),
        timeout=2,
    )
    assert r.status_code == 200
    assert "PLC-1" in r.text


def test_web_ide_program_download(plc_with_web):
    import requests

    plc, _web = plc_with_web
    r = requests.get(
        f"http://127.0.0.1:{plc._web_port}/program/download",
        auth=("openplc", "openplc"),
        timeout=2,
    )
    assert r.status_code == 200
    assert "PROGRAM intake_pump_control" in r.text


def test_web_ide_auth_required(plc_with_web):
    import requests

    plc, _web = plc_with_web
    r = requests.get(f"http://127.0.0.1:{plc._web_port}/", timeout=2)
    assert r.status_code == 401
