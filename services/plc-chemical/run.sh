#!/bin/bash
# Launch PLC-2 Chemical Dosing Controller inside the svc-plc-chemical
# network namespace. Requires sudo for ip netns exec.
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$PROJECT_DIR"

NS=svc-plc-chemical
NAME="PLC-2 Chemical Dosing Controller"

echo "[$NAME] Starting in namespace $NS..."
exec sudo PYTHONPATH="$PROJECT_DIR" ip netns exec "$NS" \
    python3 services/plc-chemical/server.py
