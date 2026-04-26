#!/bin/bash
# PLC-5 Power Feed - IEC 60870-5-104 outstation
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$PROJECT_DIR"
NS=svc-plc-power
echo "[PLC-5] Starting Power Feed IEC 104 outstation in $NS..."
exec sudo ip netns exec "$NS" python3 services/plc-power/server.py "$@"
