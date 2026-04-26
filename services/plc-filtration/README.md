# PLC-3 Filtration - DNP3 Outstation

Multi-stage sand/carbon filter controller implementing a minimal DNP3
(IEEE 1815) outstation on TCP port 20000.

## Network

| Field | Value |
|---|---|
| Namespace | `svc-plc-filter` |
| IP | `10.0.4.103` |
| Port | `20000/tcp` |
| Outstation address | `10` |
| Master address | `1` |

## Point map

See `config.yml` for the full list. Summary:

- 7 binary inputs (filter run/bypass/alarm state)
- 6 binary outputs (valve/pump commands)
- 7 analog inputs (differential pressures, turbidity, chlorine, flow)
- 3 analog outputs (setpoints)
- 3 counters (backwash cycles, swaps, totalizer)

## Run

```
./services/plc-filtration/run.sh
```

or standalone for development:

```
python3 services/plc-filtration/server.py --bind 127.0.0.1 --port 20020
```

## Tests

```
pytest services/plc-filtration/tests/
```

## Notes

This is a **teaching** outstation implemented with raw asyncio sockets
because `pydnp3` is not available on the target board. It implements enough
link-layer framing (CRC-16-DNP, 16-byte data chunks) and application-layer
response structure (Class 0 integrity poll) to be recognised by
protocol analysers and standard masters. It is not conformance-tested
against IEEE 1815.
