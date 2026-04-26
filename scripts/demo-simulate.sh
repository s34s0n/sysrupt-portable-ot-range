#!/bin/bash
# demo-simulate.sh - Auto-solve all CTF challenges with display celebrations
set -e
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_DIR"

echo "[demo] Resetting CTF state..."
redis-cli FLUSHDB > /dev/null

echo "[demo] Starting simulation - watch the display!"
printf "simulate\nquit\n" | PYTHONPATH="$PROJECT_DIR" python3 -m ctf.cli

echo "[demo] Complete!"
