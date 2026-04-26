#!/bin/bash
cd "$(dirname "$0")/app"
exec python3 server.py
