#!/usr/bin/env python3
"""
OPC-UA Gateway - IT/OT bridge
Aggregates all PLC data from Redis and exposes via OPC-UA on port 4840.
VULNERABILITY: Anonymous access, no encryption.
"""

import asyncio
import json
import logging
import os
import signal
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(os.path.dirname(_HERE))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from asyncua import Server, ua

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
log = logging.getLogger("opcua-gateway")

# ---------------------------------------------------------------------------
# Redis helper
# ---------------------------------------------------------------------------
_redis = None


def _get_redis():
    global _redis
    if _redis is not None:
        try:
            _redis.ping()
            return _redis
        except Exception:
            _redis = None
    import redis as _redis_mod
    for host in ("10.0.2.1",
                 "127.0.0.1"):
        try:
            r = _redis_mod.Redis(host=host, port=6379, decode_responses=True,
                                 socket_connect_timeout=0.1)
            r.ping()
            log.info("Redis connected at %s:6379", host)
            _redis = r
            return r
        except Exception:
            continue
    log.warning("Redis not available")
    return None


# ---------------------------------------------------------------------------
# Node tree builder
# ---------------------------------------------------------------------------
async def build_node_tree(server, idx):
    """Build the OPC-UA node tree for the water treatment plant."""
    objects = server.nodes.objects
    wtp = await objects.add_object(idx, "WaterTreatmentPlant")

    nodes = {}

    # -- PlantInfo -----------------------------------------------------------
    plant_info = await wtp.add_object(idx, "PlantInfo")
    nodes["plant_name"] = await plant_info.add_variable(
        idx, "PlantName", "Municipal Water Treatment Facility")
    nodes["plant_id"] = await plant_info.add_variable(
        idx, "PlantID", "WTP-SYSRUPT-001")
    nodes["plant_location"] = await plant_info.add_variable(
        idx, "Location", "Sysrupt Training Range")

    # Maintenance subtree with hidden flag
    maintenance = await plant_info.add_object(idx, "Maintenance")
    svc_history = await maintenance.add_object(idx, "ServiceHistory")
    entry = await svc_history.add_object(idx, "Entry_2024_03_15")
    await entry.add_variable(idx, "Date", "2024-03-15")
    await entry.add_variable(idx, "Technician", "J. Smith")
    nodes["hidden_flag"] = await entry.add_variable(
        idx, "Notes", "SYSRUPT{0pc_u4_1nt3l_g4th3r3d}")
    entry2 = await svc_history.add_object(idx, "Entry_2024_01_10")
    await entry2.add_variable(idx, "Date", "2024-01-10")
    await entry2.add_variable(idx, "Technician", "M. Johnson")
    await entry2.add_variable(idx, "Notes", "Routine calibration - all sensors OK")


    # -- HistorianConfig (information disclosure vulnerability) ----------------
    hist_config = await wtp.add_object(idx, "HistorianConfig")
    await hist_config.add_variable(idx, "Server", "10.0.2.10")
    await hist_config.add_variable(idx, "Port", 8080)
    await hist_config.add_variable(idx, "Database", "process_history.db")
    await hist_config.add_variable(idx, "Username", "historian")
    await hist_config.add_variable(idx, "Password", "hist0ry!")
    await hist_config.add_variable(idx, "Status", "Connected - Last sync 2m ago")

    # -- IntakePumps ---------------------------------------------------------
    intake = await wtp.add_object(idx, "IntakePumps")
    nodes["intake_pump1_run"] = await intake.add_variable(idx, "Pump1_Running", False)
    nodes["intake_pump2_run"] = await intake.add_variable(idx, "Pump2_Running", False)
    nodes["intake_tank_level"] = await intake.add_variable(idx, "Tank_Level_Pct", 0.0)
    nodes["intake_flow_rate"] = await intake.add_variable(idx, "Flow_Rate_LPM", 0.0)
    nodes["intake_inlet_valve"] = await intake.add_variable(idx, "Inlet_Valve", False)

    # -- ChemicalDosing ------------------------------------------------------
    chemical = await wtp.add_object(idx, "ChemicalDosing")
    nodes["chem_chlorine_ppm"] = await chemical.add_variable(idx, "Chlorine_PPM", 0.0)
    nodes["chem_ph"] = await chemical.add_variable(idx, "pH_Value", 0.0)
    nodes["chem_dosing_rate"] = await chemical.add_variable(idx, "Dosing_Rate_MLPM", 0.0)
    nodes["chem_pid_output"] = await chemical.add_variable(idx, "PID_Output_Pct", 0.0)
    nodes["chem_alarm_inhibit"] = await chemical.add_variable(idx, "AlarmInhibit", False)
    await nodes["chem_alarm_inhibit"].set_writable()  # VULNERABILITY

    # -- Filtration ----------------------------------------------------------
    filtration = await wtp.add_object(idx, "Filtration")
    nodes["filt_dp_psi"] = await filtration.add_variable(idx, "DiffPressure_PSI", 0.0)
    nodes["filt_turbidity"] = await filtration.add_variable(idx, "Turbidity_NTU", 0.0)
    nodes["filt_backwash_active"] = await filtration.add_variable(idx, "Backwash_Active", False)

    # -- Distribution --------------------------------------------------------
    distrib = await wtp.add_object(idx, "Distribution")
    nodes["dist_pressure_psi"] = await distrib.add_variable(idx, "Pressure_PSI", 0.0)
    nodes["dist_flow_rate"] = await distrib.add_variable(idx, "Flow_Rate_GPM", 0.0)
    nodes["dist_residual_cl"] = await distrib.add_variable(idx, "Residual_Chlorine", 0.0)

    # -- PowerFeed -----------------------------------------------------------
    power = await wtp.add_object(idx, "PowerFeed")
    nodes["pwr_voltage"] = await power.add_variable(idx, "Voltage_V", 0.0)
    nodes["pwr_current"] = await power.add_variable(idx, "Current_A", 0.0)
    nodes["pwr_frequency"] = await power.add_variable(idx, "Frequency_Hz", 0.0)
    nodes["pwr_breaker_closed"] = await power.add_variable(idx, "MainBreaker_Closed", True)

    # -- BuildingManagement (separate corporate network) --------------------
    sensors = await wtp.add_object(idx, "BuildingManagement")
    nodes["sens_temp_ambient"] = await sensors.add_variable(idx, "Temp_Ambient_C", 0.0)
    nodes["sens_temp_process"] = await sensors.add_variable(idx, "Temp_Process_C", 0.0)
    nodes["sens_humidity"] = await sensors.add_variable(idx, "Humidity_Pct", 0.0)

    # -- SafetySystem --------------------------------------------------------
    safety = await wtp.add_object(idx, "SafetySystem")
    nodes["sis_armed"] = await safety.add_variable(idx, "SIS_Armed", True)
    nodes["sis_tripped"] = await safety.add_variable(idx, "SIS_Tripped", False)
    nodes["sis_healthy"] = await safety.add_variable(idx, "SIS_Healthy", True)
    nodes["sis_maintenance"] = await safety.add_variable(idx, "MaintenanceMode", False)
    nodes["sis_chlorine"] = await safety.add_variable(idx, "Chlorine_PPM", 0.0)
    nodes["sis_ph"] = await safety.add_variable(idx, "pH_Value", 0.0)
    nodes["sis_level"] = await safety.add_variable(idx, "Level_Pct", 0.0)
    nodes["sis_trip_count"] = await safety.add_variable(idx, "Trip_Count", 0)

    return nodes


# ---------------------------------------------------------------------------
# Update loop - reads Redis, updates OPC-UA variables
# ---------------------------------------------------------------------------
async def _monitor_clients(server, nodes):
    """Monitor OPC-UA client connections and publish access events."""
    r = _get_redis()
    published = False
    while True:
        if not published and r:
            # Simple approach: check if any client has EVER connected
            # by monitoring the server's session count via internal API
            try:
                count = 0
                # Try different asyncua internal APIs
                try:
                    count = len(server.bserver.clients) if hasattr(server, 'bserver') and hasattr(server.bserver, 'clients') else 0
                except Exception:
                    pass
                if count == 0:
                    try:
                        count = server.bserver._policies_count if hasattr(server, 'bserver') else 0
                    except Exception:
                        pass
                # Fallback: check Redis for a marker set by the update loop
                if count == 0:
                    try:
                        marker = r.get("opcua:client_connected")
                        if marker:
                            count = 1
                    except Exception:
                        pass
                if count > 0:
                    r.publish("opcua.access", json.dumps({
                        "type": "browse",
                        "node_path": "WaterTreatmentPlant/PlantInfo/Maintenance/ServiceHistory",
                        "client_ip": "external",
                        "timestamp": time.time(),
                    }))
                    log.info("Published OPC-UA access event")
                    published = True
            except Exception as e:
                log.debug("Monitor check error: %s", e)
        await asyncio.sleep(0.5)
async def update_loop(nodes):
    """Periodically update OPC-UA variables from Redis."""
    read_count = 0
    while True:
        r = _get_redis()
        if r:
            try:
                read_count += 1
                r.set("opcua:reads", str(read_count))
                r.set("opcua:status", "running")

                # Intake PLC
                raw = r.get("plc:intake:holding")
                if raw:
                    vals = json.loads(raw)
                    if isinstance(vals, list) and len(vals) >= 7:
                        await nodes["intake_tank_level"].write_value(float(vals[0]))
                        await nodes["intake_flow_rate"].write_value(float(vals[1]) if len(vals) > 1 else 0.0)
                        await nodes["intake_pump1_run"].write_value(bool(vals[4]) if len(vals) > 4 else False)

                # Chemical PLC
                raw = r.get("plc:chemical:holding")
                if raw:
                    vals = json.loads(raw)
                    if isinstance(vals, list) and len(vals) >= 4:
                        await nodes["chem_chlorine_ppm"].write_value(float(vals[0]) / 100.0 if vals[0] else 0.0)
                        await nodes["chem_ph"].write_value(float(vals[1]) / 100.0 if vals[1] else 0.0)
                        await nodes["chem_dosing_rate"].write_value(float(vals[2]) if len(vals) > 2 else 0.0)
                        await nodes["chem_pid_output"].write_value(float(vals[3]) if len(vals) > 3 else 0.0)

                # SIS
                raw_status = r.get("sis:status")
                if raw_status:
                    await nodes["sis_armed"].write_value(raw_status == "armed")
                    await nodes["sis_tripped"].write_value(raw_status == "tripped")
                    await nodes["sis_maintenance"].write_value(raw_status == "maintenance")

                raw_sensors = r.get("sis:sensors")
                if raw_sensors:
                    s = json.loads(raw_sensors)
                    await nodes["sis_chlorine"].write_value(float(s.get("chlorine_ppm", 0)))
                    await nodes["sis_ph"].write_value(float(s.get("ph", 0)))
                    await nodes["sis_level"].write_value(float(s.get("level_pct", 0)))

                trip_count = r.get("sis:trip_count")
                if trip_count:
                    await nodes["sis_trip_count"].write_value(int(trip_count))

                # Field sensors
                raw_temp = r.get("hw:temp:temp_ambient")
                if raw_temp:
                    await nodes["sens_temp_ambient"].write_value(float(raw_temp))
                raw_temp = r.get("hw:temp:temp_process")
                if raw_temp:
                    await nodes["sens_temp_process"].write_value(float(raw_temp))

            except Exception as e:
                log.debug("Update loop error: %s", e)

        await asyncio.sleep(0.5)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
async def run_server(bind_ip="0.0.0.0", bind_port=4840):
    server = Server()
    await server.init()

    endpoint_ip = "0.0.0.0"
    endpoint = f"opc.tcp://{endpoint_ip}:{bind_port}/sysrupt/wtp"
    server.set_endpoint(endpoint)
    server.set_server_name("Sysrupt WTP OPC-UA Gateway")

    # VULNERABILITY: Allow anonymous access, no security
    server.set_security_policy([ua.SecurityPolicyType.NoSecurity])

    uri = "urn:sysrupt:wtp:opcua"
    idx = await server.register_namespace(uri)

    nodes = await build_node_tree(server, idx)

    log.info("OPC-UA server starting on %s", endpoint)


    # Hook: detect client connections via asyncua log messages
    import logging as _logging
    class _ConnHandler(_logging.Handler):
        def __init__(self):
            super().__init__()
            self._seen = set()
        def emit(self, record):
            msg = record.getMessage()
            if "New connection from" in msg and "Internal" not in msg:
                ip = "unknown"
                if "(" in msg:
                    try:
                        ip = msg.split("(")[1].split(",")[0].strip("' ")
                    except Exception:
                        pass
                if ip not in self._seen:
                    self._seen.add(ip)
                    r = _get_redis()
                    if r:
                        try:
                            r.publish("opcua.access", json.dumps({
                                "type": "browse",
                                "node_path": "WaterTreatmentPlant/PlantInfo/Maintenance/ServiceHistory",
                                "client_ip": ip,
                                "timestamp": time.time(),
                            }))
                            log.info("CTF: access event for %s", ip)
                        except Exception:
                            pass
    _h = _ConnHandler()
    _logging.getLogger("asyncua.server.binary_server_asyncio").addHandler(_h)
    _logging.getLogger("asyncua.server.internal_session").addHandler(_h)

    async with server:
        log.info("OPC-UA server running")
        r = _get_redis()
        if r:
            r.set("opcua:status", "running")
            r.set("opcua:reads", "0")
            r.set("opcua:writes", "0")
        # Start client monitor for CTF auto-detection
        # Hook into connection events via binary server
        asyncio.create_task(_monitor_clients(server, nodes))
        await update_loop(nodes)


def main():
    bind_ip = os.environ.get("BIND_IP", "0.0.0.0")
    bind_port = int(os.environ.get("BIND_PORT", "4840"))

    loop = asyncio.new_event_loop()

    def _shutdown(signum, frame):
        log.info("Shutting down (signal %d)...", signum)
        for task in asyncio.all_tasks(loop):
            task.cancel()
        sys.exit(0)

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    try:
        loop.run_until_complete(run_server(bind_ip, bind_port))
    except KeyboardInterrupt:
        pass
    except asyncio.CancelledError:
        pass
    finally:
        loop.close()


if __name__ == "__main__":
    main()
