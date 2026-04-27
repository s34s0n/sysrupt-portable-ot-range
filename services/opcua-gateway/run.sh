#!/bin/bash
# Launch OPC-UA Gateway inside the svc-opcua network namespace.
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$PROJECT_DIR"

SITE_PKGS="$(python3 -c 'import site; print(site.getusersitepackages())' 2>/dev/null || echo /usr/lib/python3/dist-packages)"
export PYTHONPATH="$SITE_PKGS:$PROJECT_DIR:$PYTHONPATH"

NS=svc-opcua
NAME="OPC-UA Gateway"

echo "[$NAME] Starting in namespace $NS..."
exec sudo PYTHONPATH="$PYTHONPATH" ip netns exec "$NS" \
    python3 services/opcua-gateway/server.py
