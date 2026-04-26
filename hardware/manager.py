"""Central hardware manager - unified API for simulated or real hardware."""
from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml

from hardware.redis_publisher import HardwareRedisPublisher
from hardware.sim_led import SimulatedLED
from hardware.sim_relay import SimulatedRelay
from hardware.sim_temperature import SimulatedTemperatureSensor


class HardwareManager:
    """
    Unified hardware interface for the OT Range.
    Runs in 'simulated' or 'real' mode based on config.
    Other modules use this exclusively - never access GPIO/I2C/Redis directly.
    """

    def __init__(self, config_path: str | None = None):
        if config_path is None:
            config_path = str(Path(__file__).parent / "config.yml")
        self.config_path = config_path
        with open(config_path) as f:
            self.config = yaml.safe_load(f)

        self.mode = self.config.get("mode", "simulated")
        self.redis_config = self.config.get("redis", {})
        self.update_interval_s = self.redis_config.get("update_interval_ms", 500) / 1000.0

        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self.start_time = time.time()

        if self.mode == "simulated":
            sim = self.config.get("simulation", {})
            self.sensors: dict[str, SimulatedTemperatureSensor] = {
                s["id"]: SimulatedTemperatureSensor(s)
                for s in sim.get("temperature", {}).get("sensors", [])
            }
            self.relays: dict[str, SimulatedRelay] = {
                r["id"]: SimulatedRelay(r) for r in sim.get("relays", [])
            }
            self.leds: dict[str, SimulatedLED] = {
                l["id"]: SimulatedLED(l) for l in sim.get("leds", [])
            }
        elif self.mode == "real":
            raise NotImplementedError(
                "Real mode not implemented yet - set mode: simulated in hardware/config.yml"
            )
        else:
            raise ValueError(f"Unknown hardware mode: {self.mode}")

        self.publisher = HardwareRedisPublisher(self.redis_config)

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                state = self.get_full_state()
                self.publisher.publish_state(state)
            except Exception:
                pass
            self._stop_event.wait(self.update_interval_s)

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        self.publisher.close()

    def get_temperature(self, sensor_id: str) -> float:
        with self._lock:
            if sensor_id not in self.sensors:
                raise KeyError(f"Unknown temperature sensor: {sensor_id}")
            return self.sensors[sensor_id].read()

    def get_all_temperatures(self) -> dict[str, float]:
        with self._lock:
            return {sid: s.read() for sid, s in self.sensors.items()}

    def set_temperature_override(self, sensor_id: str, value: float | None) -> None:
        with self._lock:
            if sensor_id not in self.sensors:
                raise KeyError(f"Unknown temperature sensor: {sensor_id}")
            if value is None:
                self.sensors[sensor_id].clear_override()
            else:
                self.sensors[sensor_id].set_override(value)

    def set_relay(self, relay_id: str, state: bool) -> None:
        with self._lock:
            if relay_id not in self.relays:
                raise KeyError(f"Unknown relay: {relay_id}")
            event = self.relays[relay_id].set_state(state)
        if event is not None:
            self.publisher.publish_event("hardware.relay.change", event)

    def get_relay(self, relay_id: str) -> bool:
        with self._lock:
            if relay_id not in self.relays:
                raise KeyError(f"Unknown relay: {relay_id}")
            return self.relays[relay_id].get_state()

    def get_all_relays(self) -> dict[str, bool]:
        with self._lock:
            return {rid: r.get_state() for rid, r in self.relays.items()}

    def set_led(self, led_id: str, state: str) -> None:
        with self._lock:
            if led_id not in self.leds:
                raise KeyError(f"Unknown LED: {led_id}")
            self.leds[led_id].set_state(state)
            info = self.leds[led_id].get_info()
        self.publisher.publish_event(
            "hardware.led.change",
            {"led_id": led_id, "state": state, "color": info["color"], "timestamp": time.time()},
        )

    def get_led(self, led_id: str) -> str:
        with self._lock:
            if led_id not in self.leds:
                raise KeyError(f"Unknown LED: {led_id}")
            return self.leds[led_id].get_state()

    def get_all_leds(self) -> dict[str, str]:
        with self._lock:
            return {lid: l.get_state() for lid, l in self.leds.items()}

    def get_full_state(self) -> dict:
        with self._lock:
            return {
                "mode": self.mode,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "temperatures": {sid: round(s.read(), 3) for sid, s in self.sensors.items()},
                "relays": {rid: r.get_state() for rid, r in self.relays.items()},
                "leds": {lid: l.get_state() for lid, l in self.leds.items()},
                "uptime_seconds": int(time.time() - self.start_time),
            }

    def reset(self) -> None:
        with self._lock:
            for r in self.relays.values():
                r.reset()
            for l in self.leds.values():
                l.reset()
            for s in self.sensors.values():
                s.clear_override()
