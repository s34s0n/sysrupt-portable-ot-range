#!/bin/bash
# Launch OPC-UA Gateway inside the svc-opcua network namespace.
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$PROJECT_DIR"

export PYTHONPATH="/home/sysrupt/.local/lib/python3.13/site-packages:$PROJECT_DIR:$PYTHONPATH"

NS=svc-opcua
NAME="OPC-UA Gateway"

echo "[$NAME] Starting in namespace $NS..."
exec sudo PYTHONPATH="$PYTHONPATH" ip netns exec "$NS" \
    python3 services/opcua-gateway/server.py
