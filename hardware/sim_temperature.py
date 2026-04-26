"""Simulated temperature sensor with noise and slow sinusoidal drift."""
from __future__ import annotations

import math
import random
import time


class SimulatedTemperatureSensor:
    """Generates realistic temperature readings with noise + slow sinusoidal drift."""

    DRIFT_PERIOD_S = 2 * 3600  # 2 hours

    def __init__(self, config: dict):
        self.id = config["id"]
        self.name = config["name"]
        self.location = config["location"]
        self.base_value_c = float(config["base_value_c"])
        self.noise_amplitude_c = float(config["noise_amplitude_c"])
        self.drift_rate_c_per_hour = float(config["drift_rate_c_per_hour"])
        self.min_c = float(config["min_c"])
        self.max_c = float(config["max_c"])
        self.start_time = time.time()
        self.override: float | None = None

    def read(self) -> float:
        noise = random.gauss(0.0, self.noise_amplitude_c)
        if self.override is not None:
            value = self.override + noise
        else:
            elapsed = time.time() - self.start_time
            drift = self.drift_rate_c_per_hour * math.sin(
                2 * math.pi * elapsed / self.DRIFT_PERIOD_S
            )
            value = self.base_value_c + drift + noise
        return max(self.min_c, min(self.max_c, value))

    def set_override(self, value: float) -> None:
        self.override = float(value)

    def clear_override(self) -> None:
        self.override = None

    def get_info(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "location": self.location,
            "base_value_c": self.base_value_c,
            "current_override": self.override,
        }
