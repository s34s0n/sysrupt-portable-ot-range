"""PLC-5 Power Feed - IEC 60870-5-104 outstation using the c104 library."""

import argparse
import json
import logging
import os
import random
import sys
import threading
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

# Keep c104 logging reasonably quiet by default.
os.environ.setdefault("PYTHONUNBUFFERED", "1")

import c104  # noqa: E402
import redis  # noqa: E402

log = logging.getLogger("plc-power")


class PowerFeedIEC104:
    PLC_NAME = "PLC-5 Power Feed IEC 60870-5-104 Outstation"
    PLC_ID = "power"

    COMMON_ADDR = 1

    def __init__(self, bind_ip: str = "0.0.0.0", bind_port: int = 2404):
        self.bind_ip = bind_ip
        self.bind_port = bind_port

        self.server = c104.Server(ip=bind_ip, port=bind_port, tick_rate_ms=200)
        self.station = self.server.add_station(common_address=self.COMMON_ADDR)

        # --- Monitored single points (M_SP_NA_1) ---
        # 100 main breaker, 101 bus tie, 102 feeder A, 103 feeder B, 104 earth switch
        self.sp_main_breaker = self.station.add_point(
            io_address=100, type=c104.Type.M_SP_NA_1, report_ms=2000
        )
        self.sp_main_breaker.value = True  # closed
        self.sp_bus_tie = self.station.add_point(
            io_address=101, type=c104.Type.M_SP_NA_1, report_ms=2000
        )
        self.sp_bus_tie.value = False
        self.sp_feeder_a = self.station.add_point(
            io_address=102, type=c104.Type.M_SP_NA_1, report_ms=2000
        )
        self.sp_feeder_a.value = True
        self.sp_feeder_b = self.station.add_point(
            io_address=103, type=c104.Type.M_SP_NA_1, report_ms=2000
        )
        self.sp_feeder_b.value = True
        self.sp_earth_switch = self.station.add_point(
            io_address=104, type=c104.Type.M_SP_NA_1, report_ms=2000
        )
        self.sp_earth_switch.value = False

        # --- Analog measurements (M_ME_NC_1 short float) ---
        # 300 voltage, 301 current, 302 active power, 303 reactive power,
        # 304 frequency, 305 power factor
        self.me_voltage = self.station.add_point(
            io_address=300, type=c104.Type.M_ME_NC_1, report_ms=5000
        )
        self.me_voltage.value = 230.0
        self.me_current = self.station.add_point(
            io_address=301, type=c104.Type.M_ME_NC_1, report_ms=5000
        )
        self.me_current.value = 42.5
        self.me_p_active = self.station.add_point(
            io_address=302, type=c104.Type.M_ME_NC_1, report_ms=5000
        )
        self.me_p_active.value = 9200.0
        self.me_p_reactive = self.station.add_point(
            io_address=303, type=c104.Type.M_ME_NC_1, report_ms=5000
        )
        self.me_p_reactive.value = 1300.0
        self.me_frequency = self.station.add_point(
            io_address=304, type=c104.Type.M_ME_NC_1, report_ms=5000
        )
        self.me_frequency.value = 50.00
        self.me_pf = self.station.add_point(
            io_address=305, type=c104.Type.M_ME_NC_1, report_ms=5000
        )
        self.me_pf.value = 0.98

        # --- Commands (C_SC_NA_1) ---
        self.cmd_main_breaker = self.station.add_point(
            io_address=400, type=c104.Type.C_SC_NA_1
        )
        self.cmd_main_breaker.on_receive(self._on_main_breaker)
        self.cmd_bus_tie = self.station.add_point(
            io_address=401, type=c104.Type.C_SC_NA_1
        )
        self.cmd_bus_tie.on_receive(self._on_bus_tie)
        self.cmd_feeder_a = self.station.add_point(
            io_address=402, type=c104.Type.C_SC_NA_1
        )
        self.cmd_feeder_a.on_receive(self._on_feeder_a)
        self.cmd_feeder_b = self.station.add_point(
            io_address=403, type=c104.Type.C_SC_NA_1
        )
        self.cmd_feeder_b.on_receive(self._on_feeder_b)

        self._stop = threading.Event()
        self._redis = None
        self._connect_redis()

    # ----------------------- redis ------------------------------------- #
    def _connect_redis(self):
        for host in ["127.0.0.1", "10.0.4.1", "10.0.5.1", "10.0.3.1", "10.0.2.1", "10.0.1.1"]:
            try:
                r = redis.Redis(
                    host=host,
                    port=6379,
                    socket_timeout=1,
                    socket_connect_timeout=1,
                    decode_responses=True,
                )
                r.ping()
                self._redis = r
                log.info("redis connected at %s", host)
                return
            except Exception:
                continue
        log.warning("redis unavailable - degraded mode")

    def _publish_event(self, event: dict):
        if not self._redis:
            return
        try:
            self._redis.publish("ot.protocol.write", json.dumps(event))
            self._redis.lpush(
                f"plc:{self.PLC_ID}:write_log", json.dumps(event)
            )
            self._redis.ltrim(f"plc:{self.PLC_ID}:write_log", 0, 999)
        except Exception:
            pass

    def _publish_state(self):
        if not self._redis:
            return
        state = {
            "plc_id": self.PLC_ID,
            "status": "running",
            "protocol": "iec-60870-5-104",
            "port": self.bind_port,
            "single_points": {
                "main_breaker": bool(self.sp_main_breaker.value),
                "bus_tie": bool(self.sp_bus_tie.value),
                "feeder_a": bool(self.sp_feeder_a.value),
                "feeder_b": bool(self.sp_feeder_b.value),
                "earth_switch": bool(self.sp_earth_switch.value),
            },
            "measurements": {
                "voltage_v": float(self.me_voltage.value or 0.0),
                "current_a": float(self.me_current.value or 0.0),
                "p_active_w": float(self.me_p_active.value or 0.0),
                "p_reactive_var": float(self.me_p_reactive.value or 0.0),
                "frequency_hz": float(self.me_frequency.value or 0.0),
                "power_factor": float(self.me_pf.value or 0.0),
            },
            "connections": self.server.open_connection_count,
            "ts": time.time(),
        }
        try:
            pipe = self._redis.pipeline()
            pipe.set(f"plc:{self.PLC_ID}:status", "running")
            pipe.set(f"plc:{self.PLC_ID}:full_state", json.dumps(state))
            pipe.execute()
        except Exception:
            pass

    # ----------------------- command callbacks ------------------------ #
    def _cmd(self, name: str, sp_point, new_value, ioa: int = 0):
        sp_point.value = bool(new_value)
        try:
            sp_point.transmit(c104.Cot.SPONTANEOUS)
        except Exception:
            pass
        self._publish_event({
            "plc_id": self.PLC_ID,
            "protocol": "iec104",
            "operation": name,
            "value": bool(new_value),
            "ioa": ioa,
            "ts": time.time(),
        })
        log.info("command %s -> %s (ioa=%d)", name, bool(new_value), ioa)
        return c104.ResponseState.SUCCESS

    def _on_main_breaker(
        self,
        point: c104.Point,
        previous_info: c104.Information,
        message: c104.IncomingMessage,
    ) -> c104.ResponseState:
        return self._cmd("main_breaker", self.sp_main_breaker, point.value, ioa=400)

    def _on_bus_tie(
        self,
        point: c104.Point,
        previous_info: c104.Information,
        message: c104.IncomingMessage,
    ) -> c104.ResponseState:
        return self._cmd("bus_tie", self.sp_bus_tie, point.value, ioa=401)

    def _on_feeder_a(
        self,
        point: c104.Point,
        previous_info: c104.Information,
        message: c104.IncomingMessage,
    ) -> c104.ResponseState:
        return self._cmd("feeder_a", self.sp_feeder_a, point.value, ioa=402)

    def _on_feeder_b(
        self,
        point: c104.Point,
        previous_info: c104.Information,
        message: c104.IncomingMessage,
    ) -> c104.ResponseState:
        return self._cmd("feeder_b", self.sp_feeder_b, point.value, ioa=403)

    # ----------------------- lifecycle --------------------------------- #
    def _update_loop(self):
        while not self._stop.is_set():
            try:
                # Small realistic fluctuations.
                self.me_voltage.value = round(230.0 + random.uniform(-2.0, 2.0), 2)
                self.me_current.value = round(42.5 + random.uniform(-1.5, 1.5), 2)
                self.me_p_active.value = round(9200.0 + random.uniform(-100.0, 100.0), 1)
                self.me_p_reactive.value = round(1300.0 + random.uniform(-40.0, 40.0), 1)
                self.me_frequency.value = round(50.0 + random.uniform(-0.05, 0.05), 3)
                self.me_pf.value = round(0.98 + random.uniform(-0.01, 0.01), 3)
                self._publish_state()
            except Exception as exc:
                log.debug("update error: %s", exc)
            self._stop.wait(5.0)

    def start(self):
        self.server.start()
        threading.Thread(target=self._update_loop, daemon=True).start()
        print(
            f"[PLC-5] IEC 60870-5-104 outstation listening on {self.bind_ip}:{self.bind_port}",
            flush=True,
        )
        self._publish_state()

    def stop(self):
        self._stop.set()
        try:
            self.server.stop()
        except Exception:
            pass


def main():
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    )
    parser = argparse.ArgumentParser()
    parser.add_argument("--bind", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=2404)
    args = parser.parse_args()

    plc = PowerFeedIEC104(bind_ip=args.bind, bind_port=args.port)
    plc.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        plc.stop()
        print("[PLC-5] stopped")


if __name__ == "__main__":
    main()
