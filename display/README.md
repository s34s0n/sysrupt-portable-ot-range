# Display Game Hub

Flask + Socket.IO web app serving the SYSRUPT OT Range scoreboard on a 320x240
ILI9341 TFT display via Chromium kiosk mode.

## Quick start

```bash
# Server only (development)
python3 -m display

# Full kiosk (production - requires DISPLAY=:0)
bash display/launcher.sh
```

The server listens on **port 5555**.

## Screens

| Screen | Duration | Trigger |
|--------|----------|---------|
| BOOT | 5 s | Startup |
| IDLE | until CTF starts | No start_time in Redis |
| PROGRESS | 10 s rotation | Active CTF |
| HINT | 8 s rotation | Active CTF |
| PLANT_MINI | 5 s rotation | Active CTF |
| FLAG_CAPTURED | 10 s interrupt | New flag in Redis |
| ATTACK_ALERT | 5 s interrupt | attack_status flag set |
| SIS_TRIP | until cleared | sis_tripped = true |
| VICTORY | permanent | victory condition met |

## State Machine

```
BOOT --(5s)--> IDLE --(ctf starts)--> ACTIVE rotation
                                       |
                                       +-- PROGRESS (10s)
                                       +-- HINT (8s)
                                       +-- PLANT_MINI (5s)

Interrupts (highest priority):
  VICTORY       -> permanent
  SIS_TRIP      -> until cleared
  FLAG_CAPTURED -> 10 seconds
  ATTACK_ALERT  -> 5 seconds
```

## Redis Keys

- `ctf:score` - integer score
- `ctf:start_time` - epoch timestamp
- `ctf:flags_captured` - JSON array of challenge IDs
- `physics:plant_state` - JSON plant state object
- `physics:victory` - JSON victory data or null

## Testing

```bash
pytest display/tests/test_display.py -v
```
