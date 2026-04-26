# PLC-1 Intake Pump Controller

Controls raw water intake from the reservoir into Tank T-101 using two
redundant centrifugal pumps (P-101A / P-101B). Supports manual, auto,
and lead-lag alternation modes with a high-high level safety interlock.

- **IP**: `10.0.4.101` (inside `svc-plc-intake` namespace)
- **Modbus TCP**: port `502`
- **Web IDE**: `http://10.0.4.101:8080` (basic auth: `openplc` / `openplc`)
- **Source of truth**: `ladder-logic/intake_pump_control.st`
- **Implementation**: Python scan cycle in `server.py` (pymodbus TCP server,
  50 ms scan period). See `../plc_common/base_plc.py`.

## Register summary

| Type        | Addr   | Name             | Default | Description                     |
|-------------|--------|------------------|---------|---------------------------------|
| Holding     | MW0    | start_setpoint   | 30      | Pump start level (% tank)       |
| Holding     | MW1    | stop_setpoint    | 80      | Pump stop level (% tank)        |
| Holding     | MW2    | low_alarm_sp     | 15      | Low-level alarm setpoint        |
| Holding     | MW3    | high_alarm_sp    | 90      | High-level alarm setpoint       |
| Holding     | MW4    | pump_mode        | 1       | 0=MAN, 1=AUTO, 2=ALT            |
| Holding     | MW5    | system_enable    | 1       | Master enable                   |
| Holding     | MW6    | active_pump      | 1       | Lead pump in ALT mode           |
| Input       | IW0    | tank_level       | 60      | Tank T-101 level %              |
| Input       | IW1    | flow_rate        | 125     | Intake flow LPM                 |
| Coil        | QX0.0  | pump1_cmd        | 0       | Pump P-101A run                 |
| Coil        | QX0.1  | pump2_cmd        | 0       | Pump P-101B run                 |
| Coil        | QX0.2  | inlet_valve      | 0       | Reservoir inlet valve           |
| Coil        | QX0.3  | outlet_valve     | 0       | Tank outlet valve               |
| Coil        | QX0.4  | alarm_low        | 0       | Low level alarm                 |
| Coil        | QX0.5  | alarm_high       | 0       | High level alarm                |

Full machine-readable layout lives in `config.yml`.

## Launch

```bash
bash services/plc-intake/run.sh
```

## Interact over Modbus

```bash
# Read holding registers (setpoints + modes)
modbus read 10.0.4.101 %MW0 10

# Read input registers (tank level, flow)
modbus read 10.0.4.101 %IW0 2

# Force pump 1 on (manual mode only)
modbus write 10.0.4.101 %QX0.0 1
```

## Web IDE

Open `http://10.0.4.101:8080/` with basic auth `openplc:openplc`. Use the
Dashboard to see status, Program to view/download/upload the `.st` file,
Monitoring for live register values.
