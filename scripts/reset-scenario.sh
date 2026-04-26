#!/bin/bash
# reset-scenario.sh - Reset the OT Range to a clean initial state
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_DIR"

echo "[reset-scenario] Resetting OT Range scenario state..."
PYTHONPATH="$PROJECT_DIR" python3 -m orchestrator reset
echo "[reset-scenario] Done."
