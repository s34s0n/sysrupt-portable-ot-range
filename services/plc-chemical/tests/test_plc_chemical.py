"""
Tests for PLC-2 Chemical. Runs on 127.0.0.1:15021 (modbus) + :18081 (web).
"""

import io
import os
import sys
import time

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(_HERE)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from pymodbus.client import ModbusTcpClient  # noqa: E402

from services.plc_chemical_server_import import ChemicalPLC  # noqa: E402
from services.plc_common.web_ide import PLCWebIDE  # noqa: E402

_PORT_COUNTER = [16020]
_WEB_PORT_COUNTER = [18180]


def _next_modbus_port():
    _PORT_COUNTER[0] += 1
    return _PORT_COUNTER[0]


def _next_web_port():
    _WEB_PORT_COUNTER[0] += 1
    return _WEB_PORT_COUNTER[0]


@pytest.fixture
def plc():
    port = _next_modbus_port()

    class TestPLC(ChemicalPLC):
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
    assert c.connect(), "failed to connect"
    return c


def test_plc_starts(plc):
    assert plc.status == "running"
    assert plc.scan_count > 0


def test_pid_auto_mode(plc):
    # Well below setpoint -> large error -> integral accumulates -> output
    plc.set_input(0, 0)  # 0.00 ppm (sp is 1.50)
    time.sleep(1.5)  # ~30 scans for integral to drive output > 5
    assert plc.get_holding(11) > 5
    assert plc.get_coil(0) is True


def test_pid_manual_mode(plc):
    plc.set_holding(9, 0)     # manual
    plc.set_holding(10, 50)   # 50% speed
    time.sleep(0.25)
    assert plc.get_holding(11) == 50
    assert plc.get_coil(0) is True


def test_alarm_inhibit(plc):
    plc.set_input(0, 450)  # 4.50 ppm > high alarm 4.00
    time.sleep(0.25)
    assert plc.get_coil(3) is True
    plc.set_holding(15, 1)  # inhibit
    time.sleep(0.25)
    assert plc.get_coil(3) is False


def test_safety_override(plc):
    plc.set_holding(9, 0)     # manual
    plc.set_holding(10, 100)  # full speed
    plc.set_input(0, 600)     # 6.00 ppm -> safety trip
    time.sleep(0.25)
    assert plc.get_coil(0) is False
    assert plc.get_holding(11) == 0


def test_hidden_flag_readable(plc):
    c = _client(plc)
    try:
        rr = c.read_holding_registers(address=28, count=2)
        assert not rr.isError()
        assert list(rr.registers) == [16723, 17481]
    finally:
        c.close()


def test_modbus_write_setpoint(plc):
    c = _client(plc)
    try:
        c.write_register(address=0, value=200)
        time.sleep(0.3)
        assert plc.get_holding(0) == 200
        # error = 200 - cl_raw(150) = 50 -> check pid_error register (signed)
        err = plc.get_holding(14)
        # unsigned storage; expect positive
        assert err == 50
    finally:
        c.close()


def test_web_ide_upload(plc_with_web):
    import requests

    plc, _web = plc_with_web
    files = {
        "file": (
            "test.st",
            io.BytesIO(b"PROGRAM test\nEND_PROGRAM\n"),
            "text/plain",
        )
    }
    r = requests.post(
        f"http://127.0.0.1:{plc._web_port}/program/upload",
        files=files,
        auth=("openplc", "openplc"),
        timeout=3,
    )
    assert r.status_code == 200
    # file should be saved next to original
    ladder_dir = os.path.dirname(os.path.abspath(plc.ST_FILE_PATH))
    uploaded = [f for f in os.listdir(ladder_dir) if f.startswith("uploaded_")]
    assert len(uploaded) >= 1
    for f in uploaded:
        os.remove(os.path.join(ladder_dir, f))
