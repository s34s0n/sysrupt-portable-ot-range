# PLC-2 Chemical Dosing Controller

PID-controlled chlorine dosing with pH monitoring. Hypochlorite is
injected downstream of the filter bank via a variable-speed metering
pump. Safety interlock stops dosing on chlorine runaway (>5.00 ppm)
regardless of operating mode.

- **IP**: `10.0.4.102` (inside `svc-plc-chemical` namespace)
- **Modbus TCP**: port `502`
- **Web IDE**: `http://10.0.4.102:8080` (basic auth: `openplc` / `openplc`)
- **Source of truth**: `ladder-logic/chlorine_dosing_pid.st`
- **Implementation**: Python PID scan cycle in `server.py` (pymodbus
  TCP server, 50 ms scan period).

Analog values are scaled integers: chlorine = ppm*100, pH = pH*100,
temperature = degC*10, flow = LPM.

## Register summary (holding)

| Addr  | Name            | Default | Description                       |
|-------|-----------------|---------|-----------------------------------|
| MW0   | cl_setpoint     | 150     | 1.50 ppm target                   |
| MW1   | cl_alarm_high   | 400     | 4.00 ppm                          |
| MW2   | cl_alarm_low    | 50      | 0.50 ppm                          |
| MW3   | ph_setpoint     | 720     | pH 7.20                           |
| MW4   | ph_alarm_high   | 850     | pH 8.50                           |
| MW5   | ph_alarm_low    | 650     | pH 6.50                           |
| MW6   | pid_kp          | 200     | 2.00                              |
| MW7   | pid_ki          | 50      | 0.50                              |
| MW8   | pid_kd          | 10      | 0.10                              |
| MW9   | pid_mode        | 1       | 0=MANUAL, 1=AUTO                  |
| MW10  | manual_speed    | 0       | 0-100 %                           |
| MW11  | pid_output      | 0       | RO PID output                     |
| MW13  | pid_integral    | 0       | RO integral accumulator (signed)  |
| MW14  | pid_error       | 0       | RO current error (signed)         |
| MW15  | alarm_inhibit   | 0       | 1 to suppress alarms              |
| MW28  | fw_flag_hi      | 16723   | Firmware build marker             |
| MW29  | fw_flag_lo      | 17481   | Firmware build marker             |

## Register summary (input)

| Addr | Name            | Default | Units          |
|------|-----------------|---------|----------------|
| IW0  | chlorine_raw    | 150     | ppm*100        |
| IW1  | temperature_raw | 263     | degC*10        |
| IW2  | ph_raw          | 720     | pH*100         |
| IW3  | flow_rate       | 125     | LPM            |

Full layout in `config.yml`.

## Launch

```bash
bash services/plc-chemical/run.sh
```

## Interact over Modbus

```bash
# Read the full holding block
modbus read 10.0.4.102 %MW0 16

# Read the chlorine analyzer
modbus read 10.0.4.102 %IW0 1

# Switch to manual and set 40% pump speed
modbus write 10.0.4.102 %MW9 0
modbus write 10.0.4.102 %MW10 40
```
