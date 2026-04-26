#!/bin/bash
# RTU Field Sensors - BACnet/IP
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$PROJECT_DIR"
NS=svc-rtu-sensors
echo "[RTU-SENSORS] Starting BACnet/IP server in $NS..."
exec sudo ip netns exec "$NS" python3 services/rtu-sensors/server.py "$@"
