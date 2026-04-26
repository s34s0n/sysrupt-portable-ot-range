"""Physics engine - orchestrates the plant simulation tick loop."""

import json
import signal
import sys
import time
import threading
from pathlib import Path

import redis
import yaml

from physics.models.water_tank import WaterTank
from physics.models.pump import PumpModel
from physics.models.chemical import ChlorineModel, PHModel
from physics.models.filter import FilterModel
from physics.models.pid import PIDController
from physics.models.power import PowerModel
from physics.models.ambient import AmbientSensors


class PhysicsEngine:
    """Deterministic, fixed-timestep water-treatment-plant simulator.

    Reads PLC states from Redis, advances all physics models, and publishes
    sensor readings back to Redis for PLCs to consume.
    """

    def __init__(self, config_path: str = None):
        if config_path is None:
            config_path = str(Path(__file__).parent / "config.yml")

        with open(config_path) as f:
            self.config = yaml.safe_load(f)

        plant = self.config.get("water_treatment_plant", {})

        # Redis connection
        self.redis = redis.Redis(host="127.0.0.1", port=6379, decode_responses=True)
        try:
            self.redis.ping()
        except redis.ConnectionError:
            print("[physics] WARNING: Redis not available, running without Redis")
            self.redis = None

        # Hardware manager (optional)
        self.hw_manager = None
        try:
            from hardware.manager import HardwareManager
            self.hw_manager = HardwareManager()
            self.hw_manager.start()
        except Exception as e:
            print(f"[physics] WARNING: HardwareManager not available: {e}")

        # Create models
        tank_cfg = plant.get("raw_water_tank", {})
        self.tank = WaterTank({
            "capacity_liters": tank_cfg.get("capacity_l", 50000),
            "initial_level_pct": 60,
            "intake_pumps": {
                "pump1": {"flow_rate_lpm": 125},
                "pump2": {"flow_rate_lpm": 125},
            },
            "outlet_max_lpm": 200,
        })

        self.pump1 = PumpModel({"flow_rate_lpm": 125, "ramp_up_time_s": 2.0, "ramp_down_time_s": 1.0})
        self.pump2 = PumpModel({"flow_rate_lpm": 125, "ramp_up_time_s": 2.0, "ramp_down_time_s": 1.0})

        chem_cfg = plant.get("chemical_treatment", {}).get("chlorine", {})
        self.chlorine = ChlorineModel({
            "max_dose_ml_min": 500,
            "concentration_mg_ml": 125,
            "decay_rate": 0.05,
            "noise_ppm": 0.02,
            "tank_volume_liters": tank_cfg.get("capacity_l", 50000),
            "initial_ppm": chem_cfg.get("setpoint_ppm", 1.5),
        })

        self.ph_model = PHModel({"initial_ph": 7.2, "noise": 0.01})

        pid_cfg = plant.get("pid_controller", {}).get("chlorine", {})
        self.pid = PIDController({
            "kp": pid_cfg.get("kp", 1.2),
            "ki": pid_cfg.get("ki", 0.3),
            "kd": pid_cfg.get("kd", 0.05),
            "setpoint": chem_cfg.get("setpoint_ppm", 1.5),
            "output_min": pid_cfg.get("output_min", 0.0),
            "output_max": pid_cfg.get("output_max", 100.0),
        })

        filt_cfg = plant.get("filtration", {})
        self.filters = FilterModel({
            "num_beds": filt_cfg.get("beds", 4),
            "backwash_threshold_kpa": 50.0,
            "dp_increase_rate": 0.01,
            "inlet_turbidity_ntu": 5.0,
        })

        self.power = PowerModel({
            "nominal_voltage": 230.0,
            "nominal_frequency": 50.0,
            "generator_start_delay_s": 10.0,
            "base_current_a": 15.0,
        })

        self.ambient = AmbientSensors({
            "base_outdoor_temp_c": 25.0,
            "temp_amplitude_c": 8.0,
            "base_humidity_pct": 60.0,
            "base_conductivity_us": 450.0,
        })

        # State
        self._running = False
        self._stop_event = threading.Event()
        self.dt = 0.1  # 100ms tick
        self.scan_times = []
        self.tick_count = 0

        # Cached states
        self._plant_state = {}
        self._victory = False
        self._attack_indicators = {}

    def _read_redis_json(self, key: str, default=None):
        """Read and parse a JSON value from Redis."""
        if self.redis is None:
            return default
        try:
            val = self.redis.get(key)
            if val is None:
                return default
            return json.loads(val)
        except (json.JSONDecodeError, redis.RedisError):
            return default

    def _read_plc_states(self) -> dict:
        """Read all PLC states from Redis. Returns safe defaults if missing."""
        # Intake PLC
        intake_coils = self._read_redis_json("plc:intake:coils")
        intake_holding = self._read_redis_json("plc:intake:holding")

        if intake_coils and len(intake_coils) >= 4:
            pump1_on = bool(intake_coils[0])
            pump2_on = bool(intake_coils[1])
            inlet_valve = bool(intake_coils[2])
            outlet_valve = bool(intake_coils[3])
            alarm_low = bool(intake_coils[4]) if len(intake_coils) > 4 else False
            alarm_high = bool(intake_coils[5]) if len(intake_coils) > 5 else False
        else:
            # Safe defaults
            pump1_on = False
            pump2_on = False
            inlet_valve = True
            outlet_valve = True
            alarm_low = False
            alarm_high = False

        # Chemical PLC
        chem_coils = self._read_redis_json("plc:chemical:coils")
        chem_holding = self._read_redis_json("plc:chemical:holding")

        if chem_coils and len(chem_coils) >= 1:
            dosing_pump = bool(chem_coils[0])
        else:
            dosing_pump = True  # Default: dosing on

        if chem_holding and len(chem_holding) >= 11:
            cl_setpoint = chem_holding[0] / 100.0 if chem_holding[0] else 1.5
            alarm_cl_high_sp = chem_holding[1] / 100.0 if len(chem_holding) > 1 else 4.0
            pid_mode = chem_holding[9] if len(chem_holding) > 9 else 0
            manual_speed = chem_holding[10] if len(chem_holding) > 10 else 0
            pid_output = chem_holding[11] if len(chem_holding) > 11 else 45
            alarm_inhibit = chem_holding[15] if len(chem_holding) > 15 else 0
            alarm_cl_high_active = bool(chem_coils[3]) if chem_coils and len(chem_coils) > 3 else False
        else:
            cl_setpoint = 1.5
            alarm_cl_high_sp = 4.0
            pid_mode = 0  # Auto
            manual_speed = 0
            pid_output = 45
            alarm_inhibit = 0
            alarm_cl_high_active = False

        # Determine dosing speed (pid_mode: 0=MANUAL, 1=AUTO)
        if pid_mode == 0:
            # Manual mode - student overrides dosing speed
            dosing_speed = manual_speed
        else:
            # Auto PID mode - PLC controls dosing
            dosing_speed = pid_output

        # Power PLC
        power_state = self._read_redis_json("plc:power:full_state")
        if power_state:
            breaker_closed = power_state.get("breaker_status", True)
        else:
            breaker_closed = True

        # Safety SIS
        sis_status = self._read_redis_json("sis:status", "armed")
        if isinstance(sis_status, str):
            sis_status = sis_status.strip('"')
        maint_mode = self._read_redis_json("sis:maintenance_mode", "false")
        if isinstance(maint_mode, str):
            maint_mode = maint_mode.strip('"')

        return {
            "pump1_on": pump1_on,
            "pump2_on": pump2_on,
            "inlet_valve": inlet_valve,
            "outlet_valve": outlet_valve,
            "alarm_low": alarm_low,
            "alarm_high": alarm_high,
            "dosing_pump": dosing_pump,
            "dosing_speed": dosing_speed,
            "cl_setpoint": cl_setpoint,
            "alarm_cl_high_sp": alarm_cl_high_sp,
            "alarm_cl_high_active": alarm_cl_high_active,
            "alarm_inhibit": alarm_inhibit,
            "pid_mode": pid_mode,
            "breaker_closed": breaker_closed,
            "sis_status": sis_status,
            "maintenance_mode": maint_mode == "true",
        }

    def _tick(self):
        """Execute one physics tick."""
        t0 = time.monotonic()

        # Read PLC states
        plc = self._read_plc_states()

        # Update pumps
        p1 = self.pump1.update(self.dt, plc["pump1_on"])
        p2 = self.pump2.update(self.dt, plc["pump2_on"])

        pumps_running = (1 if p1["running"] else 0) + (1 if p2["running"] else 0)

        # Update tank
        tank = self.tank.update(
            self.dt,
            pump1_on=p1["running"],
            pump2_on=p2["running"],
            inlet_valve_open=plc["inlet_valve"],
            outlet_valve_open=plc["outlet_valve"],
        )

        # Get ambient readings
        ambient = self.ambient.update(self.dt, pumps_running)
        water_temp = ambient["water_temp_c"]

        # Update chlorine
        total_flow = p1["flow_lpm"] + p2["flow_lpm"]
        chem = self.chlorine.update(
            self.dt,
            dosing_on=plc["dosing_pump"],
            dosing_speed_pct=plc["dosing_speed"],
            flow_lpm=total_flow,
            temperature_c=water_temp,
        )

        # Update pH
        ph_val = self.ph_model.update(self.dt, dosing_rate=chem["dosing_rate_ml_min"])

        # Update PID (for informational purposes)
        pid_state = self.pid.update(self.dt, chem["chlorine_reading"], plc["cl_setpoint"])

        # Update filters
        filt = self.filters.update(self.dt, tank["outlet_flow_lpm"])

        # Update power
        power = self.power.update(
            self.dt,
            breaker_closed=plc["breaker_closed"],
            pump_count=pumps_running,
            dosing_on=plc["dosing_pump"],
        )

        # Check victory condition
        self._victory = self._check_victory(
            chem["chlorine_ppm"],
            plc["sis_status"],
            plc["alarm_cl_high_active"],
        )

        # Check attack indicators
        self._attack_indicators = self._check_attack_indicators(
            chem["chlorine_ppm"],
            plc["sis_status"],
            plc["maintenance_mode"],
            plc["alarm_inhibit"],
            plc["alarm_cl_high_active"],
        )

        # Build plant state
        self._plant_state = {
            "timestamp": time.time(),
            "tick": self.tick_count,
            "tank": tank,
            "pump1": p1,
            "pump2": p2,
            "chemical": {
                "chlorine_ppm": chem["chlorine_ppm"],
                "chlorine_reading": chem["chlorine_reading"],
                "dosing_rate_ml_min": chem["dosing_rate_ml_min"],
                "total_dosed_ml": chem["total_dosed_ml"],
                "ph": ph_val,
                "pid": pid_state,
            },
            "filtration": filt,
            "power": power,
            "ambient": ambient,
            "safety": {
                "sis_status": plc["sis_status"],
                "maintenance_mode": plc["maintenance_mode"],
            },
            "plc_inputs": plc,
            "attack_status": {
                "victory": self._victory,
                "indicators": self._attack_indicators,
            },
        }

        # Publish to Redis
        self._publish_to_redis(plc, tank, chem, ph_val, p1, p2, filt, power, ambient)

        # Update hardware manager
        self._update_hardware(plc, p1, p2)

        # Record scan time
        scan_ms = (time.monotonic() - t0) * 1000
        self.scan_times.append(scan_ms)
        if len(self.scan_times) > 100:
            self.scan_times.pop(0)

        self.tick_count += 1

    def _publish_to_redis(self, plc, tank, chem, ph_val, p1, p2, filt, power, ambient):
        """Publish sensor readings to Redis for PLCs to consume."""
        if self.redis is None:
            return

        try:
            # Intake PLC inputs (16-bit integers)
            level_int = int(tank["level_pct"] * 100)  # 6000 = 60.00%
            flow_int = int((p1["flow_lpm"] + p2["flow_lpm"]) * 10)  # x10
            intake_inputs = {"0": level_int, "1": flow_int}
            self.redis.publish("physics:plc:intake:inputs", json.dumps(intake_inputs))

            # Chemical PLC inputs
            cl_x100 = int(chem["chlorine_reading"] * 100)
            temp_x10 = int(ambient["water_temp_c"] * 10)
            ph_x100 = int(ph_val * 100)
            flow_x10 = int((p1["flow_lpm"] + p2["flow_lpm"]) * 10)
            chem_inputs = {"0": cl_x100, "1": temp_x10, "2": ph_x100, "3": flow_x10}
            self.redis.publish("physics:plc:chemical:inputs", json.dumps(chem_inputs))

            # SIS inputs
            sis_inputs = {
                "chlorine": cl_x100,
                "ph": ph_x100,
                "level": level_int,
            }
            self.redis.publish("physics:sis:inputs", json.dumps(sis_inputs))

            # Filtration inputs
            filt_inputs = {}
            for i, bed in enumerate(filt.get("beds", [])):
                filt_inputs[str(i)] = int(bed["dp_kpa"] * 100)
            filt_inputs["turbidity"] = int(filt["turbidity_out_ntu"] * 100)
            self.redis.publish("physics:plc:filtration:inputs", json.dumps(filt_inputs))

            # Distribution inputs
            dist_inputs = {
                "0": level_int,
                "1": flow_int,
                "2": int(power["voltage_v"] * 10),
            }
            self.redis.publish("physics:plc:distribution:inputs", json.dumps(dist_inputs))

            # Power inputs
            power_inputs = {
                "voltage": int(power["voltage_v"] * 10),
                "frequency": int(power["frequency_hz"] * 100),
                "current": int(power["current_a"] * 100),
                "power": int(power["active_power_kw"] * 100),
            }
            self.redis.publish("physics:plc:power:inputs", json.dumps(power_inputs))

            # BACnet sensor inputs
            sensor_inputs = {
                "outdoor_temp": int(ambient["outdoor_temp_c"] * 10),
                "indoor_temp": int(ambient["indoor_temp_c"] * 10),
                "humidity": int(ambient["humidity_pct"] * 10),
                "vibration": int(ambient["pump_vibration_mm_s"] * 100),
                "conductivity": int(ambient["water_conductivity_us"]),
                "water_temp": int(ambient["water_temp_c"] * 10),
            }
            self.redis.publish("physics:bms:sensors:inputs", json.dumps(sensor_inputs))

            # Full plant state (for HMI/CLI)
            self.redis.set("physics:plant_state", json.dumps(self._plant_state))
            self.redis.publish("physics:state", json.dumps(self._plant_state))

            # Set victory key for CTF engine detection
            if self._victory:
                victory_data = {
                    "chlorine_ppm": self._plant_state.get("chemical", {}).get("chlorine_ppm", 0),
                    "timestamp": time.time(),
                    "indicators": self._attack_indicators,
                }
                self.redis.set("physics:victory", json.dumps(victory_data))

        except redis.RedisError as e:
            print(f"[physics] Redis publish error: {e}")

    def _update_hardware(self, plc, p1, p2):
        """Update hardware manager state."""
        if self.hw_manager is None:
            return
        try:
            self.hw_manager.set_relay("relay1", p1["running"])
            self.hw_manager.set_relay("relay2", p2["running"])
        except Exception:
            pass

    def _check_victory(self, chlorine_ppm: float, sis_status: str,
                       alarm_cl_high_active: bool) -> bool:
        """Check if victory condition is met.

        Victory: chlorine > 8.0 AND SIS not tripped AND alarm_cl_high not active.
        """
        return (
            chlorine_ppm > 8.0
            and sis_status != "tripped"
            and not alarm_cl_high_active
        )

    def _check_attack_indicators(self, chlorine_ppm: float, sis_status: str,
                                  maintenance_mode: bool, alarm_inhibit: int,
                                  alarm_cl_high_active: bool) -> dict:
        """Check for signs of an attack in progress."""
        indicators = {}

        if chlorine_ppm > 4.0:
            indicators["chlorine_rising"] = True
            indicators["chlorine_level"] = "dangerous" if chlorine_ppm > 8.0 else "elevated"

        if maintenance_mode:
            indicators["safety_bypassed"] = True

        if sis_status == "maintenance":
            indicators["sis_in_maintenance"] = True

        if alarm_inhibit:
            indicators["alarms_suppressed"] = True

        if chlorine_ppm > 8.0 and not alarm_cl_high_active:
            indicators["alarm_should_be_active"] = True

        return indicators

    def build_plant_state(self) -> dict:
        """Return the current plant state dict (for testing)."""
        return dict(self._plant_state)

    def run(self):
        """Main loop - runs until SIGINT/SIGTERM."""
        self._running = True

        def _signal_handler(sig, frame):
            print(f"\n[physics] Received signal {sig}, shutting down...")
            self._running = False
            self._stop_event.set()

        signal.signal(signal.SIGINT, _signal_handler)
        signal.signal(signal.SIGTERM, _signal_handler)

        print("[physics] Physics engine starting...")
        print(f"[physics] Tick rate: {1/self.dt:.0f} Hz (dt={self.dt}s)")
        print(f"[physics] Tank capacity: {self.tank.capacity} L")
        print(f"[physics] Initial chlorine: {self.chlorine.chlorine_ppm} ppm")

        try:
            while self._running:
                tick_start = time.monotonic()
                self._tick()

                # Sleep for remainder of tick period
                elapsed = time.monotonic() - tick_start
                sleep_time = self.dt - elapsed
                if sleep_time > 0:
                    self._stop_event.wait(sleep_time)

                # Print stats every 100 ticks
                if self.tick_count % 100 == 0 and self.scan_times:
                    avg_ms = sum(self.scan_times) / len(self.scan_times)
                    max_ms = max(self.scan_times)
                    cl = self._plant_state.get("chemical", {}).get("chlorine_ppm", "?")
                    lvl = self._plant_state.get("tank", {}).get("level_pct", "?")
                    print(f"[physics] tick={self.tick_count} avg={avg_ms:.1f}ms "
                          f"max={max_ms:.1f}ms Cl={cl} level={lvl}%")

        except Exception as e:
            print(f"[physics] Error: {e}")
            import traceback
            traceback.print_exc()
        finally:
            self._shutdown()

    def _shutdown(self):
        """Clean shutdown."""
        print("[physics] Shutting down...")
        self._running = False
        if self.hw_manager:
            try:
                self.hw_manager.stop()
            except Exception:
                pass
        print("[physics] Physics engine stopped.")

    def stop(self):
        """Stop the engine from another thread."""
        self._running = False
        self._stop_event.set()


if __name__ == "__main__":
    engine = PhysicsEngine()
    engine.run()
