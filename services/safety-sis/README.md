# safety-sis

**Zone:** `safety`
**IP:** `10.0.5.201`
**Port:** `102`
**Protocol:** `s7comm`

Safety Instrumented System - trip logic (S7comm)

## Architecture

The SIS monitors chlorine, pH, and tank level readings and will trip (shut down
the plant) if any value exceeds its safety setpoint for longer than the
configured delay.  Once tripped, the state is **latched** and requires a manual
reset.

### S7comm Data Blocks

| DB  | Name           | Size | Description                         |
|-----|----------------|------|-------------------------------------|
| DB1 | Safety Status  | 64 B | Armed/tripped/healthy flags, sensor readings, counters |
| DB2 | Setpoints      | 32 B | Trip thresholds, delay, auto-reset, maintenance password |
| DB3 | Trip History   | 128B | Ring buffer of last 8 trip events   |
| DB99| Hidden Flag    | 32 B | Encoded flag data                   |

### HMI

Flask web interface on port **8082** showing real-time SIS status, sensor
readings, setpoints, and trip history.  Basic auth required.

## Vulnerabilities (INSTRUCTOR ONLY)

- Setpoints writable via S7comm without authentication
- Maintenance bypass with known password (7777) + maintenance bit
- Process zone can reach safety zone on port 102 (firewall misconfiguration)
