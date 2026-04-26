"""Water tank model for the water treatment plant simulation."""

import random


class WaterTank:
    """Simulates a raw water storage tank with inlet/outlet flows."""

    def __init__(self, config: dict):
        self.capacity = config.get("capacity_liters", 50000)
        initial_pct = config.get("initial_level_pct", 60)
        self.volume = self.capacity * initial_pct / 100.0

        pumps_cfg = config.get("intake_pumps", {})
        self.pump_flows = {}
        for name, pcfg in pumps_cfg.items():
            self.pump_flows[name] = pcfg.get("flow_rate_lpm", 125)

        self.outlet_max_lpm = config.get("outlet_max_lpm", 200)
        self.overflow = False

    @property
    def level_pct(self) -> float:
        return (self.volume / self.capacity) * 100.0 if self.capacity > 0 else 0.0

    def update(self, dt: float, pump1_on: bool, pump2_on: bool,
               inlet_valve_open: bool, outlet_valve_open: bool,
               outlet_pct: float = 100.0) -> dict:
        """Update tank state. dt in seconds."""
        dt_min = dt / 60.0

        # Inlet flow = sum of active pumps * inlet valve
        inlet_flow = 0.0
        pump_keys = list(self.pump_flows.keys())
        if pump1_on and len(pump_keys) > 0:
            inlet_flow += self.pump_flows[pump_keys[0]]
        if pump2_on and len(pump_keys) > 1:
            inlet_flow += self.pump_flows[pump_keys[1]]

        if not inlet_valve_open:
            inlet_flow = 0.0

        # Outlet flow with head factor
        head_factor = self.level_pct / 100.0
        if outlet_valve_open:
            outlet_flow = self.outlet_max_lpm * (outlet_pct / 100.0) * head_factor
        else:
            outlet_flow = 0.0

        # Update volume
        self.volume += (inlet_flow - outlet_flow) * dt_min

        # Clamp - slight overflow allowed (105%)
        max_vol = self.capacity * 1.05
        self.overflow = self.volume > self.capacity
        if self.volume > max_vol:
            self.volume = max_vol
        if self.volume < 0:
            self.volume = 0.0

        return {
            "level_pct": round(self.level_pct, 2),
            "inlet_flow_lpm": round(inlet_flow, 2),
            "outlet_flow_lpm": round(outlet_flow, 2),
            "volume_liters": round(self.volume, 2),
            "overflow": self.overflow,
        }
