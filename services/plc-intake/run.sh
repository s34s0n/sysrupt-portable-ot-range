#!/bin/bash
# Launch PLC-1 Intake Pump Controller inside the svc-plc-intake
# network namespace. Requires sudo for ip netns exec.
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$PROJECT_DIR"

NS=svc-plc-intake
NAME="PLC-1 Intake Pump Controller"

echo "[$NAME] Starting in namespace $NS..."
exec sudo PYTHONPATH="$PROJECT_DIR" ip netns exec "$NS" \
    python3 services/plc-intake/server.py
