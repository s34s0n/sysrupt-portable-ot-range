"""Ambient environmental sensors simulation."""

import math
import random
import time


class AmbientSensors:
    """Simulates ambient environmental conditions."""

    def __init__(self, config: dict = None):
        config = config or {}
        self.base_outdoor_temp = config.get("base_outdoor_temp_c", 25.0)
        self.temp_amplitude = config.get("temp_amplitude_c", 8.0)
        self.base_humidity = config.get("base_humidity_pct", 60.0)
        self.base_conductivity = config.get("base_conductivity_us", 450.0)

        self._start_time = time.time()

    def update(self, dt: float, pumps_running: int = 0,
               water_temp: float = 25.0) -> dict:
        """Update ambient sensor readings."""
        elapsed = time.time() - self._start_time

        # Outdoor temp with daily sine cycle (accelerated: 1 hour = 1 day)
        daily_phase = (elapsed / 3600.0) * 2 * math.pi
        outdoor_temp = self.base_outdoor_temp + self.temp_amplitude * math.sin(daily_phase)
        outdoor_temp += random.uniform(-0.5, 0.5)

        # Indoor temp slightly cooler
        indoor_temp = outdoor_temp - 2.0 + random.uniform(-0.3, 0.3)

        # Humidity inversely correlated with temp
        humidity = self.base_humidity - (outdoor_temp - self.base_outdoor_temp) * 2.0
        humidity += random.uniform(-2.0, 2.0)
        humidity = max(20.0, min(95.0, humidity))

        # Pump vibration
        base_vibration = 0.5  # mm/s
        pump_vibration = base_vibration + pumps_running * 2.5
        pump_vibration += random.uniform(-0.3, 0.3)
        if pumps_running == 0:
            pump_vibration = random.uniform(0.1, 0.5)

        # Water conductivity
        conductivity = self.base_conductivity + random.uniform(-10.0, 10.0)

        # Water temperature (influenced by ambient)
        water_t = water_temp + random.uniform(-0.1, 0.1)

        return {
            "outdoor_temp_c": round(outdoor_temp, 1),
            "indoor_temp_c": round(indoor_temp, 1),
            "humidity_pct": round(humidity, 1),
            "pump_vibration_mm_s": round(pump_vibration, 2),
            "water_conductivity_us": round(conductivity, 1),
            "water_temp_c": round(water_t, 1),
        }
