# PLC-4 Distribution - EtherNet/IP (CIP)

Distribution network pump controller exposing an EtherNet/IP server on
TCP/UDP port 44818, backed by `cpppo`.

## Network

| Field | Value |
|---|---|
| Namespace | `svc-plc-distrib` |
| IP | `10.0.4.104` |
| Port | `44818/tcp`, `44818/udp` (ListIdentity) |

## Tags

See `config.yml`. Nine INT[10] arrays:

- `OUTLET_PRESSURE`, `BOOSTER_FLOW`, `RESERVOIR_LEVEL`, `DIST_TEMP`,
  `SYSTEM_STATUS` (status/reads)
- `OUTLET_VALVE_CMD`, `BOOSTER_PUMP_SPEED`, `PRESSURE_SP`, `MODE_SELECT`
  (writable)

## Run

```
./services/plc-distribution/run.sh
```

Test with cpppo's client:

```
python3 -m cpppo.server.enip.client --address 10.0.4.104 OUTLET_PRESSURE
```

## Tests

```
pytest services/plc-distribution/tests/
```

## Notes

`cpppo`'s EtherNet/IP server runs as a subprocess. The parent process
supervises it, drives simulated physics, and publishes state to Redis.
