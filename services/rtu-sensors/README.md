# Building Management System - BACnet/IP

Building Management System (BMS) on the corporate network, advertising
HVAC, lighting, and access-control sensors as a BACnet/IP device
(`bacpypes3`).

## Network

| Field | Value |
|---|---|
| Namespace | `svc-rtu-sensors` |
| IP | `10.0.1.20` |
| Zone | Corporate (`br-corp`) |
| Port | `47808/udp` |
| Device ID | `110` |
| Vendor ID | `999` |

## Objects

See `config.yml`.

- 8 `analog-input` objects (ambient, cabinet, raw-water readings, tank level)
- 4 `binary-input` objects (door contact, flood, UPS, smoke)

## Run

```
./services/rtu-sensors/run.sh
```

Discover from the default namespace:

```
python3 -c "import BAC0, time; b = BAC0.lite(); time.sleep(2); print(b.discover())"
```

## Tests

```
pytest services/rtu-sensors/tests/
```
