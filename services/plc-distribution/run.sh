#!/bin/bash
# PLC-4 Distribution - EtherNet/IP server
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$PROJECT_DIR"
NS=svc-plc-distrib
echo "[PLC-4] Starting Distribution EtherNet/IP server in $NS..."
exec sudo ip netns exec "$NS" python3 services/plc-distribution/server.py "$@"
