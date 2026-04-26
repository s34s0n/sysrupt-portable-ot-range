#!/bin/bash
# PLC-3 Filtration - DNP3 outstation
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$PROJECT_DIR"
NS=svc-plc-filter
echo "[PLC-3] Starting Filtration DNP3 outstation in $NS..."
exec sudo ip netns exec "$NS" python3 services/plc-filtration/server.py "$@"
