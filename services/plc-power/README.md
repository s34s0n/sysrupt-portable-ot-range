# PLC-5 Power Feed - IEC 60870-5-104 Outstation

Substation/feeder gateway exposing switchgear state and electrical
measurements over IEC 60870-5-104 (`c104` library).

## Network

| Field | Value |
|---|---|
| Namespace | `svc-plc-power` |
| IP | `10.0.4.105` |
| Port | `2404/tcp` |
| Common address | `1` |

## Points

See `config.yml`.

- Single points (M_SP_NA_1) at IOA 100..104: main breaker, bus tie, feeder A/B, earth switch
- Short-float measurements (M_ME_NC_1) at IOA 300..305: voltage, current, active power, reactive power, frequency, power factor
- Single commands (C_SC_NA_1) at IOA 400..403

## Run

```
./services/plc-power/run.sh
```

## Tests

```
pytest services/plc-power/tests/
```
