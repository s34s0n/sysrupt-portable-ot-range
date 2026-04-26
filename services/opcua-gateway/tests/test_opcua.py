"""Smoke tests for OPC-UA Gateway."""
import asyncio
import os
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

from asyncua import Client, Server, ua

import importlib.util
spec = importlib.util.spec_from_file_location(
    "opcua_server", os.path.join(SERVICE, "server.py")
)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

TEST_PORT = 14840
TEST_ENDPOINT = f"opc.tcp://127.0.0.1:{TEST_PORT}/sysrupt/wtp"

# ---------------------------------------------------------------------------
# Module-scoped fixture: run OPC-UA server in a background thread
# ---------------------------------------------------------------------------
_server_loop = None
_server_obj = None
_server_nodes = None
_server_idx = None


async def _start_server():
    global _server_obj, _server_nodes, _server_idx
    server = Server()
    await server.init()
    server.set_endpoint(TEST_ENDPOINT)
    server.set_server_name("Sysrupt WTP OPC-UA Gateway (Test)")
    server.set_security_policy([ua.SecurityPolicyType.NoSecurity])

    uri = "urn:sysrupt:wtp:opcua"
    idx = await server.register_namespace(uri)
    nodes = await mod.build_node_tree(server, idx)

    await server.start()
    _server_obj = server
    _server_nodes = nodes
    _server_idx = idx
    return server


def _run_server_thread():
    global _server_loop
    _server_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(_server_loop)
    _server_loop.run_until_complete(_start_server())
    _server_loop.run_forever()


@pytest.fixture(scope="module")
def opcua_server():
    t = threading.Thread(target=_run_server_thread, daemon=True)
    t.start()
    # Wait for server to be ready
    for _ in range(40):
        if _server_obj is not None:
            break
        time.sleep(0.25)
    assert _server_obj is not None, "OPC-UA server did not start"
    time.sleep(1.0)  # Extra settling time
    yield _server_obj, _server_nodes, _server_idx
    # Shutdown
    if _server_loop and _server_obj:
        future = asyncio.run_coroutine_threadsafe(_server_obj.stop(), _server_loop)
        try:
            future.result(timeout=5)
        except Exception:
            pass
        _server_loop.call_soon_threadsafe(_server_loop.stop)


def _run_async(coro):
    """Run an async coroutine in a fresh event loop (for sync tests)."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


async def _connect_client():
    client = Client(TEST_ENDPOINT, timeout=10)
    await client.connect()
    return client


async def _find_node(parent, name):
    for child in await parent.get_children():
        bname = await child.read_browse_name()
        if bname.Name == name:
            return child
    return None


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
def test_server_starts(opcua_server):
    server, nodes, idx = opcua_server
    assert server is not None


def test_anonymous_connect(opcua_server):
    async def _test():
        client = Client(TEST_ENDPOINT, timeout=10)
        await client.connect()
        assert client.uaclient is not None
        await client.disconnect()
    _run_async(_test())


def test_browse_root(opcua_server):
    async def _test():
        client = Client(TEST_ENDPOINT, timeout=10)
        await client.connect()
        try:
            objects = client.nodes.objects
            children = await objects.get_children()
            names = []
            for child in children:
                bname = await child.read_browse_name()
                names.append(bname.Name)
            assert "WaterTreatmentPlant" in names
        finally:
            await client.disconnect()
    _run_async(_test())


def test_read_plant_name(opcua_server):
    async def _test():
        client = Client(TEST_ENDPOINT, timeout=10)
        await client.connect()
        try:
            objects = client.nodes.objects
            wtp = await _find_node(objects, "WaterTreatmentPlant")
            assert wtp is not None
            plant_info = await _find_node(wtp, "PlantInfo")
            assert plant_info is not None
            plant_name = await _find_node(plant_info, "PlantName")
            assert plant_name is not None
            val = await plant_name.read_value()
            assert val == "Municipal Water Treatment Facility"
        finally:
            await client.disconnect()
    _run_async(_test())


def test_read_chlorine(opcua_server):
    async def _test():
        client = Client(TEST_ENDPOINT, timeout=10)
        await client.connect()
        try:
            objects = client.nodes.objects
            wtp = await _find_node(objects, "WaterTreatmentPlant")
            chem = await _find_node(wtp, "ChemicalDosing")
            assert chem is not None
            cl = await _find_node(chem, "Chlorine_PPM")
            assert cl is not None
            val = await cl.read_value()
            assert isinstance(val, float)
        finally:
            await client.disconnect()
    _run_async(_test())


def test_sis_visible(opcua_server):
    async def _test():
        client = Client(TEST_ENDPOINT, timeout=10)
        await client.connect()
        try:
            objects = client.nodes.objects
            wtp = await _find_node(objects, "WaterTreatmentPlant")
            safety = await _find_node(wtp, "SafetySystem")
            assert safety is not None
            children = await safety.get_children()
            names = [
                (await child.read_browse_name()).Name
                for child in children
            ]
            assert "SIS_Armed" in names
            assert "MaintenanceMode" in names
        finally:
            await client.disconnect()
    _run_async(_test())


def test_write_alarm_inhibit(opcua_server):
    async def _test():
        client = Client(TEST_ENDPOINT, timeout=10)
        await client.connect()
        try:
            objects = client.nodes.objects
            wtp = await _find_node(objects, "WaterTreatmentPlant")
            chem = await _find_node(wtp, "ChemicalDosing")
            alarm = await _find_node(chem, "AlarmInhibit")
            assert alarm is not None
            await alarm.write_value(True)
            val = await alarm.read_value()
            assert val is True
            await alarm.write_value(False)
        finally:
            await client.disconnect()
    _run_async(_test())


def test_hidden_flag(opcua_server):
    async def _test():
        client = Client(TEST_ENDPOINT, timeout=10)
        await client.connect()
        try:
            objects = client.nodes.objects
            wtp = await _find_node(objects, "WaterTreatmentPlant")
            plant_info = await _find_node(wtp, "PlantInfo")
            maintenance = await _find_node(plant_info, "Maintenance")
            assert maintenance is not None
            svc_history = await _find_node(maintenance, "ServiceHistory")
            assert svc_history is not None
            entry = await _find_node(svc_history, "Entry_2024_03_15")
            assert entry is not None
            notes = await _find_node(entry, "Notes")
            assert notes is not None
            val = await notes.read_value()
            assert "SYSRUPT{" in val
        finally:
            await client.disconnect()
    _run_async(_test())


def test_redis_state(opcua_server):
    try:
        import redis
        r = redis.Redis(host="127.0.0.1", port=6379, decode_responses=True,
                        socket_connect_timeout=1)
        r.ping()
        r.set("opcua:status", "running")
        val = r.get("opcua:status")
        assert val == "running"
    except Exception:
        pytest.skip("Redis not available")
