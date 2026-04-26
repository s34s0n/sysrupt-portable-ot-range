"""Generate realistic historical process data."""
import sqlite3
import math
import random
from datetime import datetime, timedelta


def seed(db_path):
    db = sqlite3.connect(db_path)
    count = db.execute("SELECT COUNT(*) FROM process_data").fetchone()[0]
    if count > 0:
        db.close()
        return count

    random.seed(42)
    base_time = datetime(2026, 3, 6, 0, 0, 0)
    rows = []

    for i in range(1000):
        ts = base_time + timedelta(minutes=30 * i)
        hour = ts.hour + ts.minute / 60.0
        day_frac = i / 48.0  # day index

        # Diurnal demand pattern
        demand = 0.7 + 0.3 * math.sin((hour - 6) * math.pi / 12)
        if hour < 5 or hour > 23:
            demand *= 0.6

        # Tank level: oscillates with demand
        tank_base = 72.0
        tank_level = tank_base + 8 * math.sin(2 * math.pi * hour / 24) - 3 * demand
        tank_level += random.gauss(0, 0.5)
        tank_level = max(40, min(95, tank_level))

        # Chlorine: steady with slight variation
        chlorine = 2.5 + 0.3 * math.sin(2 * math.pi * hour / 24)
        chlorine += random.gauss(0, 0.08)
        chlorine = max(1.5, min(4.0, chlorine))

        # pH: stable around 7.2
        ph = 7.2 + 0.15 * math.sin(2 * math.pi * hour / 12)
        ph += random.gauss(0, 0.05)

        # Temperature: seasonal + diurnal
        temp = 18.0 + 3 * math.sin(2 * math.pi * day_frac / 30) + 1.5 * math.sin(2 * math.pi * hour / 24)
        temp += random.gauss(0, 0.3)

        # Flow rate
        flow = 850 * demand + random.gauss(0, 15)
        flow = max(300, min(1200, flow))

        # Filter differential pressure (increases slowly, resets on "backwash")
        filter_cycle = (i % 96) / 96.0
        filter_dp = 5.0 + 10.0 * filter_cycle + random.gauss(0, 0.3)

        # Distribution pressure
        dist_pressure = 65.0 - 5 * demand + random.gauss(0, 0.8)

        source = random.choice(["intake", "chemical", "filtration", "distribution"])

        rows.append((
            ts.strftime("%Y-%m-%d %H:%M:%S"),
            source,
            round(tank_level, 2),
            round(chlorine, 3),
            round(ph, 2),
            round(temp, 1),
            round(flow, 1),
            round(filter_dp, 2),
            round(dist_pressure, 1)
        ))

    db.executemany(
        "INSERT INTO process_data (timestamp,source,tank_level,chlorine_ppm,ph,temperature,flow_rate,filter_dp,distribution_pressure) VALUES (?,?,?,?,?,?,?,?,?)",
        rows
    )
    db.commit()
    n = db.execute("SELECT COUNT(*) FROM process_data").fetchone()[0]
    db.close()
    return n


if __name__ == "__main__":
    import sys
    path = sys.argv[1] if len(sys.argv) > 1 else "historian.db"
    print(f"Seeded {seed(path)} rows")
