"""Power system model - mains, UPS, generator."""

import random


class PowerModel:
    """Simulates electrical power supply with mains, UPS, and backup generator."""

    def __init__(self, config: dict = None):
        config = config or {}
        self.nominal_voltage = config.get("nominal_voltage", 230.0)
        self.nominal_frequency = config.get("nominal_frequency", 50.0)
        self.generator_start_delay = config.get("generator_start_delay_s", 10.0)

        self.breaker_closed = True
        self.generator_running = False
        self.ups_active = False
        self._breaker_open_time = 0.0
        self._generator_timer = 0.0

        # Load tracking
        self.base_current = config.get("base_current_a", 15.0)

    def update(self, dt: float, breaker_closed: bool,
               pump_count: int = 0, dosing_on: bool = False) -> dict:
        """Update power state. dt in seconds."""
        prev_breaker = self.breaker_closed
        self.breaker_closed = breaker_closed

        if not self.breaker_closed:
            # Track how long breaker has been open
            if prev_breaker:
                # Just opened
                self._breaker_open_time = 0.0
                self._generator_timer = 0.0
                self.generator_running = False
                self.ups_active = True

            self._breaker_open_time += dt
            self._generator_timer += dt

            # Generator starts after delay
            if self._generator_timer >= self.generator_start_delay:
                self.generator_running = True

            if self.generator_running:
                # Generator power
                voltage = 225.0 + random.uniform(-3.0, 3.0)
                frequency = self.nominal_frequency + random.uniform(-0.3, 0.3)
                self.ups_active = False
            elif self.ups_active:
                # UPS power (limited)
                voltage = 210.0 + random.uniform(-5.0, 5.0)
                frequency = self.nominal_frequency + random.uniform(-0.1, 0.1)
            else:
                # No power
                voltage = 0.0
                frequency = 0.0
        else:
            # Normal mains power
            self.generator_running = False
            self.ups_active = False
            self._breaker_open_time = 0.0
            self._generator_timer = 0.0
            voltage = self.nominal_voltage + random.uniform(-2.0, 2.0)
            frequency = self.nominal_frequency + random.uniform(-0.1, 0.1)

        # Current based on load
        if voltage > 0:
            current = self.base_current + pump_count * 8.0 + (3.0 if dosing_on else 0.0)
            current += random.uniform(-0.5, 0.5)
        else:
            current = 0.0

        # Power
        active_power = voltage * current / 1000.0  # kW

        return {
            "voltage_v": round(voltage, 1),
            "frequency_hz": round(frequency, 2),
            "current_a": round(current, 2),
            "active_power_kw": round(active_power, 2),
            "breaker_closed": self.breaker_closed,
            "generator_running": self.generator_running,
            "ups_active": self.ups_active,
        }
