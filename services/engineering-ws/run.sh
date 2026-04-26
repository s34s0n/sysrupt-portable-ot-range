#!/bin/bash
# Engineering Workstation - launcher
# Starts the safety bridge (background) and SSH setup.
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "[eng-ws] Starting safety bridge..."
python3 "$SCRIPT_DIR/safety_bridge.py" &
BRIDGE_PID=$!

echo "[eng-ws] Running SSH setup..."
bash "$SCRIPT_DIR/setup_ssh.sh" || true

echo "[eng-ws] Engineering Workstation ready (bridge PID=$BRIDGE_PID)"
wait
