#!/bin/bash
# Launch Safety SIS (S7comm server + HMI) inside their respective namespaces.
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$PROJECT_DIR"

export PYTHONPATH="/home/sysrupt/.local/lib/python3.13/site-packages:$PROJECT_DIR:$PYTHONPATH"

NS_PLC=svc-safety-plc
NS_HMI=svc-safety-hmi
NAME="Safety SIS"

echo "[$NAME] Starting S7comm server in namespace $NS_PLC..."
sudo PYTHONPATH="$PYTHONPATH" ip netns exec "$NS_PLC" \
    python3 services/safety-sis/server.py &
PLC_PID=$!

echo "[$NAME] Starting HMI in namespace $NS_HMI..."
sudo PYTHONPATH="$PYTHONPATH" ip netns exec "$NS_HMI" \
    python3 services/safety-sis/hmi.py &
HMI_PID=$!

cleanup() {
    echo "[$NAME] Stopping..."
    kill $PLC_PID $HMI_PID 2>/dev/null || true
    wait $PLC_PID $HMI_PID 2>/dev/null || true
    echo "[$NAME] Stopped."
}
trap cleanup EXIT INT TERM

echo "[$NAME] Running (PLC PID=$PLC_PID, HMI PID=$HMI_PID)"
wait
