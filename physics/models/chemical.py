"""Chemical dosing models - chlorine and pH simulation."""

import random


class ChlorineModel:
    """Simulates free chlorine concentration in the treatment tank.

    Core equation: dCl/dt = dosing_input - decay - dilution
    - Dosing: rate * 125 mg/mL * dt_min / volume
    - Decay: first-order with temperature factor
    - Dilution: Cl * (flow * dt_min) / volume * 0.1
    """

    def __init__(self, config: dict):
        self.max_dose_ml_min = config.get("max_dose_ml_min", 500)
        self.concentration_mg_ml = config.get("concentration_mg_ml", 125)  # 12.5% NaOCl
        self.decay_rate = config.get("decay_rate", 0.05)  # per hour
        self.noise_ppm = config.get("noise_ppm", 0.02)
        self.volume = config.get("tank_volume_liters", 50000)

        self.chlorine_ppm = config.get("initial_ppm", 1.5)
        self.total_dosed_ml = 0.0
        self._dosing_rate = 0.0

    def update(self, dt: float, dosing_on: bool, dosing_speed_pct: float,
               flow_lpm: float, temperature_c: float = 25.0) -> dict:
        """Update chlorine concentration. dt in seconds."""
        dt_min = dt / 60.0
        dt_hours = dt / 3600.0

        # Dosing input
        if dosing_on and dosing_speed_pct > 0:
            self._dosing_rate = self.max_dose_ml_min * (dosing_speed_pct / 100.0)
        else:
            self._dosing_rate = 0.0

        # mL dosed this step
        ml_dosed = self._dosing_rate * dt_min
        self.total_dosed_ml += ml_dosed

        # ppm added = (mL * mg/mL) / (volume_liters * 1000 mg/g ... wait, ppm = mg/L)
        # mg added = ml_dosed * concentration_mg_ml
        # ppm added = mg_added / volume_liters  (since 1 ppm = 1 mg/L)
        if self.volume > 0:
            ppm_added = (ml_dosed * self.concentration_mg_ml) / self.volume
        else:
            ppm_added = 0.0

        # Decay: first-order with temperature factor
        # Higher temp = faster decay
        temp_factor = 1.0 + (temperature_c - 20.0) * 0.02
        temp_factor = max(0.5, temp_factor)
        decay = self.chlorine_ppm * self.decay_rate * temp_factor * dt_hours

        # Dilution from flow
        if self.volume > 0 and flow_lpm > 0:
            dilution = self.chlorine_ppm * (flow_lpm * dt_min) / self.volume * 0.1
        else:
            dilution = 0.0

        # Update
        self.chlorine_ppm += ppm_added - decay - dilution
        self.chlorine_ppm = max(0.0, self.chlorine_ppm)

        # Sensor reading with noise
        reading = self.chlorine_ppm + random.uniform(-self.noise_ppm, self.noise_ppm)
        reading = max(0.0, reading)

        return {
            "chlorine_ppm": round(self.chlorine_ppm, 4),
            "chlorine_reading": round(reading, 4),
            "dosing_rate_ml_min": round(self._dosing_rate, 2),
            "total_dosed_ml": round(self.total_dosed_ml, 2),
        }


class PHModel:
    """Simulates pH of treated water."""

    def __init__(self, config: dict = None):
        config = config or {}
        self.ph = config.get("initial_ph", 7.2)
        self.noise = config.get("noise", 0.01)
        self.drift_rate = config.get("drift_rate", 0.001)  # drift toward neutral per second

    def update(self, dt: float, dosing_rate: float = 0.0) -> float:
        """Update pH. Dosing raises pH slightly. Returns pH value."""
        # Dosing effect (NaOCl is alkaline, raises pH)
        self.ph += dosing_rate * 0.0001 * dt

        # Natural drift toward 7.0
        drift = (7.0 - self.ph) * self.drift_rate * dt
        self.ph += drift

        # Clamp
        self.ph = max(5.0, min(10.0, self.ph))

        # Return with noise
        reading = self.ph + random.uniform(-self.noise, self.noise)
        reading = max(5.0, min(10.0, reading))
        return round(reading, 2)
