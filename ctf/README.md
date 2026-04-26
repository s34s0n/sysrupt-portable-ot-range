# ctf/ -- Auto-Detection CTF Engine

Capture-The-Flag auto-detection engine for the Sysrupt OT Range.  Watches
Redis events from all services and automatically awards challenges when
students complete them.  No manual flag submission required.

## Architecture

Three daemon threads:

1. **Pub/sub listener** -- subscribes to `modbus.write`, `ot.protocol.write`,
   `sis.write`, `sis.maintenance`, `opcua.access`, `bms.access`
2. **Polling loop** -- checks `corp:admin_login`, `scada:hmi_login`,
   `physics:victory` keys every second
3. **Hint timer** -- unlocks hints at 15/30/45 min elapsed

## Challenges

| ID | Points | Name | Trigger |
|----|--------|------|---------|
| 01 | 100 | perimeter_breach | `corp:admin_login` key exists |
| 02 | 200 | intelligence_gathering | `opcua.access` with ServiceHistory |
| 03 | 300 | pivot_to_ot | `scada:hmi_login` key exists |
| 04 | 350 | building_recon_bacnet | `bms.access` with AV:99 |
| 05 | 400 | deep_protocol_dnp3 | `ot.protocol.write` DNP3 operate |
| 06 | 450 | deep_protocol_enip | `ot.protocol.write` ENIP class 100 |
| 07 | 500 | deep_protocol_iec104 | `ot.protocol.write` IEC104 IOA 400 |
| 08 | 600 | process_manipulation_modbus | Modbus write addr=9,val=0 AND addr=10,val>50 |
| 09 | 800 | safety_system_assault | SIS maintenance enabled OR DB2 setpoint > 800 |
| 10 | 1000 | full_compromise_stuxnet | `physics:victory` key exists |

**Total: 4700 points**

## Running

```bash
# Engine daemon
python3 -m ctf

# CLI
python3 -m ctf.cli
```

## CLI Commands

- `status` -- show challenge table with colors
- `reset` -- clear all CTF state
- `award N` -- manually award challenge N
- `simulate` -- demo mode, award all 10 with 3s delays
- `monitor` -- live-updating status table
- `quit` -- exit

## Redis State

- `ctf:score` -- current total score
- `ctf:flags_captured` -- JSON list of captured challenge IDs
- `ctf:start_time` -- epoch timestamp of first capture
- `ctf:last_flag_time` -- epoch of most recent capture
- `ctf:challenge:{id}` -- JSON detail per solved challenge
- `ctf:active` -- "1" when engine is running
- `ctf:hint_state` -- JSON with current hint level and elapsed time
- `ctf:flag_captured` -- pub/sub channel for display celebrations

## Tests

```bash
cd ~/sysrupt-ot-range
python3 -m pytest ctf/tests/ -v
```
