"""Filtration bed model with differential pressure and backwash."""

import random


class FilterBed:
    """Single filter bed with DP tracking."""

    def __init__(self, bed_id: int):
        self.bed_id = bed_id
        self.dp_kpa = 5.0  # Initial differential pressure
        self.active = True
        self.backwashing = False
        self.backwash_timer = 0.0
        self.backwash_duration = 300.0  # 5 minutes
        self.cycles = 0

    def to_dict(self) -> dict:
        return {
            "bed_id": self.bed_id,
            "dp_kpa": round(self.dp_kpa, 2),
            "active": self.active,
            "backwashing": self.backwashing,
            "cycles": self.cycles,
        }


class FilterModel:
    """Simulates a multi-bed filtration system."""

    def __init__(self, config: dict):
        self.num_beds = config.get("num_beds", 4)
        self.backwash_threshold = config.get("backwash_threshold_kpa", 50.0)
        self.dp_increase_rate = config.get("dp_increase_rate", 0.01)  # kPa per LPM per second

        self.beds = [FilterBed(i) for i in range(self.num_beds)]
        self.inlet_turbidity = config.get("inlet_turbidity_ntu", 5.0)

    def update(self, dt: float, flow_lpm: float, auto_backwash: bool = True) -> dict:
        """Update all filter beds. dt in seconds."""
        # Per-bed flow
        active_beds = [b for b in self.beds if b.active and not b.backwashing]
        if not active_beds:
            active_beds = [b for b in self.beds if not b.backwashing]

        flow_per_bed = flow_lpm / len(active_beds) if active_beds else 0.0

        currently_backwashing = any(b.backwashing for b in self.beds)

        for bed in self.beds:
            if bed.backwashing:
                # Continue backwash
                bed.backwash_timer += dt
                if bed.backwash_timer >= bed.backwash_duration:
                    bed.backwashing = False
                    bed.active = True
                    bed.dp_kpa = 5.0 + random.uniform(-0.5, 0.5)
                    bed.backwash_timer = 0.0
                    bed.cycles += 1
                continue

            if bed.active:
                # DP increases with flow and time
                bed.dp_kpa += self.dp_increase_rate * flow_per_bed * dt / 60.0
                # Add small random walk
                bed.dp_kpa += random.uniform(-0.01, 0.02) * dt

                # Auto-backwash if threshold exceeded (only one at a time)
                if auto_backwash and bed.dp_kpa >= self.backwash_threshold and not currently_backwashing:
                    bed.backwashing = True
                    bed.active = False
                    bed.backwash_timer = 0.0
                    currently_backwashing = True

        # Turbidity reduction: efficiency based on average DP
        active_beds = [b for b in self.beds if b.active and not b.backwashing]
        if active_beds:
            avg_dp = sum(b.dp_kpa for b in active_beds) / len(active_beds)
            efficiency = max(0.0, 1.0 - avg_dp / 100.0)
            turbidity_out = self.inlet_turbidity * (1.0 - efficiency * 0.95)
        else:
            turbidity_out = self.inlet_turbidity

        return {
            "beds": [b.to_dict() for b in self.beds],
            "turbidity_out_ntu": round(turbidity_out, 3),
            "active_count": len(active_beds),
            "backwashing_count": sum(1 for b in self.beds if b.backwashing),
        }

    def start_backwash(self, bed_id: int) -> bool:
        """Manually start backwash on a specific bed."""
        if any(b.backwashing for b in self.beds):
            return False  # Only one at a time
        for bed in self.beds:
            if bed.bed_id == bed_id and not bed.backwashing:
                bed.backwashing = True
                bed.active = False
                bed.backwash_timer = 0.0
                return True
        return False
