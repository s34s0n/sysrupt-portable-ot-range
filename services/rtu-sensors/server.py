"""RTU Field Sensors - BACnet/IP server using bacpypes3."""

import argparse
import asyncio
import json
import logging
import os
import random
import sys
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import redis  # noqa: E402
from bacpypes3.argparse import SimpleArgumentParser  # noqa: E402
from bacpypes3.app import Application  # noqa: E402
from bacpypes3.local.analog import AnalogInputObject, AnalogValueObject  # noqa: E402
from bacpypes3.local.binary import BinaryInputObject  # noqa: E402

log = logging.getLogger("rtu-sensors")


AI_DEFS = [
    (0, "ambient_temp_c", 24.5, "degreesCelsius"),
    (1, "ambient_humidity", 56.0, "percentRelativeHumidity"),
    (2, "cabinet_temp_c", 31.2, "degreesCelsius"),
    (3, "raw_water_temp_c", 14.8, "degreesCelsius"),
    (4, "raw_water_ph", 7.2, "noUnits"),
    (5, "raw_water_turbidity", 18.0, "noUnits"),
    (6, "raw_water_conductivity", 420.0, "microSiemens"),
    (7, "tank_level_pct", 82.0, "percent"),
]

BI_DEFS = [
    (0, "door_contact", False),
    (1, "flood_sensor", False),
    (2, "ups_on_battery", False),
    (3, "smoke_alarm", False),
]


class FieldSensorsBACnet:
    PLC_NAME = "Building Management System - BACnet/IP"
    PLC_ID = "sensors"  # kept for backwards compat
    REDIS_KEY_PREFIX = "bms"
    DEVICE_ID = 110

    def __init__(self, bind_address: str = "host:47808", device_id: int = 110):
        self.bind_address = bind_address
        self.device_id = device_id
        self.app: Application | None = None
        self.ais = []
        self.bis = []
        self.running = False

        self._redis = None
        self._connect_redis()

    def _connect_redis(self):
        for host in ["127.0.0.1", "10.0.1.1", "10.0.4.1", "10.0.5.1", "10.0.3.1", "10.0.2.1"]:
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

    def _publish_state(self):
        if not self._redis:
            return
        ais = {name: float(obj.presentValue) for (_, name, _, _), obj in zip(AI_DEFS, self.ais)}
        bis_ = {name: bool(obj.presentValue) for (_, name, _), obj in zip(BI_DEFS, self.bis)}
        state = {
            "plc_id": self.PLC_ID,
            "status": "running",
            "protocol": "bacnet-ip",
            "device_id": self.device_id,
            "analog_inputs": ais,
            "binary_inputs": bis_,
            "ts": time.time(),
        }
        try:
            pipe = self._redis.pipeline()
            pipe.set(f"{self.REDIS_KEY_PREFIX}:{self.PLC_ID}:status", "running")
            pipe.set(f"{self.REDIS_KEY_PREFIX}:{self.PLC_ID}:full_state", json.dumps(state))
            # Backwards-compat plc:* key so the HMI can find it.
            pipe.set(f"plc:{self.PLC_ID}:status", "running")
            pipe.set(f"plc:{self.PLC_ID}:full_state", json.dumps(state))
            pipe.execute()
        except Exception:
            pass

    def _build_app(self) -> Application:
        parser = SimpleArgumentParser()
        args = parser.parse_args([
            "--name", "WTP-BMS-01",
            "--instance", str(self.device_id),
            "--address", self.bind_address,
            "--vendoridentifier", "999",
        ])
        app = Application.from_args(args)

        for idx, name, default, units in AI_DEFS:
            obj = AnalogInputObject(
                objectIdentifier=("analog-input", idx),
                objectName=name,
                presentValue=default,
                units=units,
                description=f"Field sensor {name}",
            )
            app.add_object(obj)
            self.ais.append(obj)

        for idx, name, default in BI_DEFS:
            obj = BinaryInputObject(
                objectIdentifier=("binary-input", idx),
                objectName=name,
                presentValue=("active" if default else "inactive"),
                description=f"Field sensor {name}",
            )
            app.add_object(obj)
            self.bis.append(obj)

        # CTF: Add hidden analog-value object AV:99
        self._av99 = AnalogValueObject(
            objectIdentifier=("analog-value", 99),
            objectName="hidden_config_backup",
            presentValue=42.0,
            units="noUnits",
            description="SYSRUPT{b4cn3t_bu1ld1ng_m4n4g3m3nt}",
        )
        app.add_object(self._av99)

        return app

    async def _scan_loop(self):
        while self.running:
            try:
                # Drift analog inputs slightly.
                self.ais[0].presentValue = round(24.5 + random.uniform(-0.8, 0.8), 2)
                self.ais[1].presentValue = round(56.0 + random.uniform(-2.0, 2.0), 1)
                self.ais[2].presentValue = round(31.2 + random.uniform(-0.6, 0.6), 2)
                self.ais[3].presentValue = round(14.8 + random.uniform(-0.2, 0.2), 2)
                self.ais[4].presentValue = round(7.2 + random.uniform(-0.05, 0.05), 3)
                self.ais[5].presentValue = round(18.0 + random.uniform(-1.0, 1.0), 2)
                self.ais[6].presentValue = round(420.0 + random.uniform(-5.0, 5.0), 1)
                self.ais[7].presentValue = round(82.0 + random.uniform(-0.3, 0.3), 2)
                self._publish_state()
            except Exception as exc:
                log.debug("scan err: %s", exc)
            await asyncio.sleep(5.0)

    async def _monitor_av99(self):
        """Hook into Application to detect ReadProperty requests."""
        # Wait for app to be ready
        while not self.app:
            await asyncio.sleep(1)
        
        # Wait for CTF engine to subscribe
        await asyncio.sleep(30)
        
        published = False
        
        # Monkey-patch the application confirmation handler
        original_confirmation = getattr(self.app, 'confirmation', None)
        
        async def _ctf_hook(*args, **kwargs):
            nonlocal published
            if not published and self._redis:
                try:
                    self._redis.publish("bms.access", json.dumps({
                        "type": "flag_object_read",
                        "object": "AV:99",
                        "property": "description",
                        "client_ip": "external",
                        "timestamp": time.time(),
                    }))
                    log.info("CTF: BACnet ReadProperty detected")
                    published = True
                except Exception:
                    pass
            if original_confirmation:
                return await original_confirmation(*args, **kwargs)
        
        # Hook into indication (incoming request handler)
        original_indication = self.app.indication
        
        async def _indication_hook(apdu):
            nonlocal published
            if not published and self._redis:
                try:
                    self._redis.publish("bms.access", json.dumps({
                        "type": "flag_object_read",
                        "object": "AV:99",
                        "property": "description",
                        "client_ip": "external",
                        "timestamp": time.time(),
                    }))
                    log.info("CTF: BACnet request detected via indication hook")
                    published = True
                except Exception:
                    pass
            return await original_indication(apdu)
        
        try:
            self.app.indication = _indication_hook
            log.info("CTF: BACnet indication hook installed")
        except Exception as e:
            log.warning("CTF: Could not install hook: %s", e)
        
        # Keep running; indication hook above handles publishing
        while self.running:
            await asyncio.sleep(5.0)

    async def start(self):
        self.app = self._build_app()
        self.running = True
        self._publish_state()
        print(
            f"[BMS] BACnet/IP device {self.device_id} on {self.bind_address}",
            flush=True,
        )
        asyncio.create_task(self._scan_loop())
        asyncio.create_task(self._monitor_av99())
        # Run forever.
        await asyncio.Future()


def main():
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    )
    parser = argparse.ArgumentParser()
    parser.add_argument("--bind", default="host:47808", help="BACnet bind address, e.g. host:47808")
    parser.add_argument("--device-id", type=int, default=110)
    args = parser.parse_args()

    rtu = FieldSensorsBACnet(bind_address=args.bind, device_id=args.device_id)
    try:
        asyncio.run(rtu.start())
    except KeyboardInterrupt:
        rtu.running = False
        print("[BMS] stopped")


if __name__ == "__main__":
    main()
