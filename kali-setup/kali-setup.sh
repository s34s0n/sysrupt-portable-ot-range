#!/bin/bash
# ==========================================================
# Sysrupt OT Range - Kali Student Laptop Setup
# Run this on a fresh Kali to install all tools needed
# for the 10 CTF challenges.
#
# Usage: sudo bash kali-setup.sh
# ==========================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "╔═════════════════════════════════════╗"
echo "║  SYSRUPT OT RANGE - KALI SETUP     ║"
echo "╚═════════════════════════════════════╝"
echo ""

if [ "$EUID" -ne 0 ]; then
    echo "[ERROR] Run as root: sudo bash kali-setup.sh"
    exit 1
fi

# System packages
echo "[1/4] Installing system packages..."
apt update -qq
apt install -y -qq \
    sshpass \
    libsnap7-dev libsnap7-1 \
    nmap \
    2>/dev/null || true

# Python libraries for OT protocols
echo "[2/4] Installing Python OT libraries..."
pip install --break-system-packages \
    opcua \
    opcua-client \
    pymodbus \
    python-snap7 \
    c104 \
    cpppo \
    2>/dev/null

# Copy OT tools to home directory
echo "[3/4] Installing OT protocol tools..."
USER_HOME="/home/$(logname 2>/dev/null || echo kali)"
TOOLS_DIR="$USER_HOME/tools"
mkdir -p "$TOOLS_DIR"
for tool in bacnet-tool.py dnp3-tool.py enip-tool.py iec104-tool.py modbus-tool.py s7comm-tool.py; do
    # Check in tools/ subfolder first, then current dir
    if [ -f "$SCRIPT_DIR/tools/$tool" ]; then
        cp "$SCRIPT_DIR/tools/$tool" "$TOOLS_DIR/"
        chmod +x "$TOOLS_DIR/$tool"
    elif [ -f "$SCRIPT_DIR/$tool" ]; then
        cp "$SCRIPT_DIR/$tool" "$TOOLS_DIR/"
        chmod +x "$TOOLS_DIR/$tool"
    fi
done
# Also copy tools to home dir for easy access
for tool in "$TOOLS_DIR"/*.py; do
    ln -sf "$tool" "$USER_HOME/$(basename $tool)" 2>/dev/null
done
chown -R "$(logname 2>/dev/null || echo kali):$(logname 2>/dev/null || echo kali)" "$TOOLS_DIR" "$USER_HOME"/*.py 2>/dev/null || true

# Enable SSH (so instructor can connect remotely)
echo "[4/4] Enabling SSH..."
systemctl enable ssh --now 2>/dev/null || true

echo ""
echo "╔══════════════════════════════════════════╗"
echo "║  SETUP COMPLETE                          ║"
echo "║                                          ║"
echo "║  Libraries installed:                    ║"
echo "║  • nmap         - network scanner        ║"
echo "║  • opcua-client - OPC-UA GUI browser     ║"
echo "║  • pymodbus     - Modbus TCP client      ║"
echo "║  • python-snap7  - S7comm client         ║"
echo "║  • c104         - IEC 104 client         ║"
echo "║  • cpppo        - EtherNet/IP client     ║"
echo "║  • sshpass      - SSH with passwords     ║"
echo "║                                          ║"
echo "║  OT Protocol Tools (~/tools/):           ║"
echo "║  • bacnet-tool.py  - BACnet/IP explorer  ║"
echo "║  • dnp3-tool.py   - DNP3 explorer        ║"
echo "║  • enip-tool.py   - EtherNet/IP explorer ║"
echo "║  • iec104-tool.py - IEC 104 explorer     ║"
echo "║  • modbus-tool.py - Modbus TCP explorer  ║"
echo "║  • s7comm-tool.py - S7comm explorer      ║"
echo "║                                          ║"
echo "║  Run: python3 ~/tools/<tool> -h          ║"
echo "║  GUI: opcua-client                       ║"
echo "║                                          ║"
echo "║  Plug in Ethernet and start hacking!     ║"
echo "╚══════════════════════════════════════════╝"
