"""Live monitoring CLI for the physics engine."""

import json
import sys
import time

import redis


def color(text: str, code: str) -> str:
    """Wrap text in ANSI color."""
    return f"\033[{code}m{text}\033[0m"


def green(text: str) -> str:
    return color(text, "32")


def yellow(text: str) -> str:
    return color(text, "33")


def red(text: str) -> str:
    return color(text, "31")


def cyan(text: str) -> str:
    return color(text, "36")


def bold(text: str) -> str:
    return color(text, "1")


def bar_graph(pct: float, width: int = 30) -> str:
    """Create a bar graph string."""
    filled = int(pct / 100.0 * width)
    filled = max(0, min(width, filled))
    empty = width - filled
    bar = "\u2588" * filled + "\u2591" * empty
    if pct > 90:
        return red(f"[{bar}] {pct:.1f}%")
    elif pct > 70:
        return yellow(f"[{bar}] {pct:.1f}%")
    else:
        return green(f"[{bar}] {pct:.1f}%")


def cl_color(ppm: float) -> str:
    """Color chlorine reading based on level."""
    text = f"{ppm:.2f} ppm"
    if ppm > 5.0:
        return red(text)
    elif ppm > 2.0:
        return yellow(text)
    else:
        return green(text)


def main():
    """Main CLI loop."""
    r = redis.Redis(host="127.0.0.1", port=6379, decode_responses=True)

    try:
        r.ping()
    except redis.ConnectionError:
        print("ERROR: Cannot connect to Redis at 127.0.0.1:6379")
        sys.exit(1)

    print("Connecting to physics engine...")

    try:
        while True:
            # Clear screen
            sys.stdout.write("\033[2J\033[H")

            raw = r.get("physics:plant_state")
            if raw is None:
                print(bold("SYSRUPT OT RANGE - PHYSICS MONITOR"))
                print()
                print(yellow("Waiting for physics engine..."))
                print("Start with: python3 -m physics.engine")
                time.sleep(1)
                continue

            try:
                state = json.loads(raw)
            except json.JSONDecodeError:
                print(red("Error parsing plant state"))
                time.sleep(1)
                continue

            # Header
            print(bold("=" * 60))
            print(bold("  SYSRUPT OT RANGE - WATER TREATMENT PLANT"))
            print(bold("=" * 60))
            print()

            # Tank
            tank = state.get("tank", {})
            level = tank.get("level_pct", 0)
            print(bold("TANK"))
            print(f"  Level:  {bar_graph(level)}")
            print(f"  Volume: {tank.get('volume_liters', 0):.0f} L / {50000} L")
            print(f"  Inlet:  {tank.get('inlet_flow_lpm', 0):.1f} LPM")
            print(f"  Outlet: {tank.get('outlet_flow_lpm', 0):.1f} LPM")
            if tank.get("overflow"):
                print(f"  {red('*** OVERFLOW ***')}")
            print()

            # Pumps
            p1 = state.get("pump1", {})
            p2 = state.get("pump2", {})
            p1_str = green("[ON]") if p1.get("running") else "[off]"
            p2_str = green("[ON]") if p2.get("running") else "[off]"
            print(bold("PUMPS"))
            print(f"  P1:{p1_str} {p1.get('flow_lpm', 0):.1f} LPM  "
                  f"Temp:{p1.get('motor_temp_c', 0):.1f}C  "
                  f"Hours:{p1.get('runtime_hours', 0):.2f}")
            print(f"  P2:{p2_str} {p2.get('flow_lpm', 0):.1f} LPM  "
                  f"Temp:{p2.get('motor_temp_c', 0):.1f}C  "
                  f"Hours:{p2.get('runtime_hours', 0):.2f}")
            print()

            # Chemical
            chem = state.get("chemical", {})
            cl_ppm = chem.get("chlorine_ppm", 0)
            dosing_str = green("[ON]") if chem.get("dosing_rate_ml_min", 0) > 0 else "[off]"
            pid = chem.get("pid", {})
            pid_mode_str = "MANUAL" if state.get("plc_inputs", {}).get("pid_mode") == 1 else "AUTO"
            print(bold("CHEMICAL"))
            print(f"  Cl:     {cl_color(cl_ppm)}")
            print(f"  pH:     {chem.get('ph', 0):.2f}")
            print(f"  Dosing: {dosing_str} {chem.get('dosing_rate_ml_min', 0):.0f} mL/min  "
                  f"PID:{pid_mode_str}  Output:{pid.get('output', 0):.1f}%")
            print(f"  Total:  {chem.get('total_dosed_ml', 0):.0f} mL dosed")
            print()

            # Filtration
            filt = state.get("filtration", {})
            beds = filt.get("beds", [])
            print(bold("FILTRATION"))
            bed_strs = []
            for b in beds:
                if b.get("backwashing"):
                    bed_strs.append(yellow(f"F{b['bed_id']}:[BW]"))
                else:
                    dp = b.get("dp_kpa", 0)
                    bed_strs.append(f"F{b['bed_id']}:{dp:.1f}")
            print(f"  Beds:      {' '.join(bed_strs)} kPa")
            print(f"  Turbidity: {filt.get('turbidity_out_ntu', 0):.3f} NTU")
            print()

            # Power
            pwr = state.get("power", {})
            if pwr.get("generator_running"):
                src = yellow("[GEN]")
            elif pwr.get("ups_active"):
                src = yellow("[UPS]")
            elif pwr.get("breaker_closed"):
                src = green("[MAINS]")
            else:
                src = red("[NO POWER]")
            print(bold("POWER"))
            print(f"  {pwr.get('voltage_v', 0):.0f}V  {pwr.get('frequency_hz', 0):.1f}Hz  "
                  f"{pwr.get('current_a', 0):.1f}A  {pwr.get('active_power_kw', 0):.1f}kW  {src}")
            print()

            # Ambient
            amb = state.get("ambient", {})
            print(bold("ENVIRONMENT"))
            print(f"  Outdoor: {amb.get('outdoor_temp_c', 0):.1f}C  "
                  f"Indoor: {amb.get('indoor_temp_c', 0):.1f}C  "
                  f"Humidity: {amb.get('humidity_pct', 0):.0f}%")
            print(f"  Water:   {amb.get('water_temp_c', 0):.1f}C  "
                  f"Cond: {amb.get('water_conductivity_us', 0):.0f} uS/cm  "
                  f"Vib: {amb.get('pump_vibration_mm_s', 0):.1f} mm/s")
            print()

            # Safety
            safety = state.get("safety", {})
            sis = safety.get("sis_status", "unknown")
            if sis == "armed":
                sis_str = green("SIS:[ARMED]")
            elif sis == "tripped":
                sis_str = red("SIS:[TRIPPED]")
            elif sis == "maintenance":
                sis_str = yellow("SIS:[MAINT]")
            else:
                sis_str = f"SIS:[{sis}]"
            print(bold("SAFETY"))
            print(f"  {sis_str}")
            if safety.get("maintenance_mode"):
                print(f"  {yellow('Maintenance mode ACTIVE')}")
            print()

            # Attack status
            attack = state.get("attack_status", {})
            indicators = attack.get("indicators", {})
            if attack.get("victory"):
                print(red(bold("*** VICTORY CONDITION MET ***")))
                print(red("  Chlorine has been raised to dangerous levels!"))
                print()
            if indicators:
                print(bold("ATTACK INDICATORS"))
                for k, v in indicators.items():
                    print(f"  {red('!')} {k}: {v}")
                print()

            # Tick info
            print(f"Tick: {state.get('tick', 0)}")
            print(cyan("Press Ctrl+C to exit"))

            time.sleep(1)

    except KeyboardInterrupt:
        print("\nExiting CLI.")


if __name__ == "__main__":
    main()
