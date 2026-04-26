"""Centrifugal pump model with ramp-up/down and thermal simulation."""

import random


class PumpModel:
    """Simulates a centrifugal pump with motor temperature and ramp behavior."""

    def __init__(self, config: dict):
        self.max_flow_lpm = config.get("flow_rate_lpm", 125)
        self.ramp_up_time = config.get("ramp_up_time_s", 2.0)
        self.ramp_down_time = config.get("ramp_down_time_s", 1.0)
        self.max_temp = config.get("max_temp_c", 65.0)
        self.min_temp = config.get("min_temp_c", 25.0)
        self.noise_pct = config.get("noise_pct", 0.02)

        self.current_flow_pct = 0.0  # 0-1 ramp factor
        self.motor_temp = self.min_temp
        self.runtime_hours = 0.0
        self.running = False
        self._commanded_on = False

    def update(self, dt: float, commanded_on: bool) -> dict:
        """Update pump state. dt in seconds."""
        self._commanded_on = commanded_on

        # Ramp up/down
        if commanded_on:
            ramp_rate = dt / self.ramp_up_time if self.ramp_up_time > 0 else 1.0
            self.current_flow_pct = min(1.0, self.current_flow_pct + ramp_rate)
        else:
            ramp_rate = dt / self.ramp_down_time if self.ramp_down_time > 0 else 1.0
            self.current_flow_pct = max(0.0, self.current_flow_pct - ramp_rate)

        self.running = self.current_flow_pct > 0.01

        # Flow with noise
        if self.running:
            noise = 1.0 + random.uniform(-self.noise_pct, self.noise_pct)
            flow = self.max_flow_lpm * self.current_flow_pct * noise
            self.runtime_hours += dt / 3600.0
        else:
            flow = 0.0

        # Motor temperature
        if self.running:
            # Heat up toward max_temp
            temp_rate = (self.max_temp - self.motor_temp) * 0.02 * dt
            self.motor_temp += temp_rate
        else:
            # Cool down toward min_temp
            temp_rate = (self.motor_temp - self.min_temp) * 0.01 * dt
            self.motor_temp -= temp_rate

        self.motor_temp = max(self.min_temp, min(self.max_temp, self.motor_temp))

        return {
            "flow_lpm": round(flow, 2),
            "motor_temp_c": round(self.motor_temp, 2),
            "runtime_hours": round(self.runtime_hours, 4),
            "running": self.running,
        }
