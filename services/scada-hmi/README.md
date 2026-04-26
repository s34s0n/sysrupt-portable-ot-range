# SCADA HMI

Real-time process dashboard for CWA water treatment plant.

## Running

```bash
./run.sh
```

Listens on port 8080 (set PORT env var to override).

## Credentials
- operator / scada_op!

## Features
- Live SVG process flow diagram
- WebSocket updates every 500ms from Redis
- Alarm log with high chlorine detection
- Trend charts
