#!/bin/bash
# Run the full Sysrupt OT Range test suite.
set -e
cd "$(dirname "${BASH_SOURCE[0]}")/.."
python3 -m pytest -q
