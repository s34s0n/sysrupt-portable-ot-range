#!/bin/bash
# Engineering Workstation - SSH setup for CTF scenario.
# Creates an "engineer" user with weak credentials and plants
# reconnaissance breadcrumbs in bash_history.
set -e

EWS_IP="${EWS_IP:-10.0.3.20}"

# Create user if not exists
if ! id engineer >/dev/null 2>&1; then
    useradd -m -s /bin/bash engineer
    echo "engineer:eng2024!" | chpasswd
fi

# /etc/hosts breadcrumbs (do NOT give away safety network)
cat >> /etc/hosts << EOF
# OT plant hosts
10.0.4.101   plc-intake
10.0.4.102   plc-chemical
10.0.4.103   plc-filtration
10.0.4.104   plc-distribution
10.0.4.105   plc-power
10.0.3.10    scada-hmi
10.0.2.10    historian
10.0.2.30    opcua-gw
EOF

# Plant recon commands in bash_history as breadcrumbs
cat > /home/engineer/.bash_history << EOF
ping -c2 plc-intake
ss -tlnp
nmap -sV 10.0.4.101 -p 502
python3 -c "from pymodbus.client import ModbusTcpClient; c=ModbusTcpClient(10.0.4.101); c.connect(); print(c.read_holding_registers(0,10))"
curl http://scada-hmi:8080/api/status
cat /etc/hosts
ip addr
EOF
chown engineer:engineer /home/engineer/.bash_history

# Start sshd (if not already running on this IP)
mkdir -p /run/sshd
if ! ss -tlnp | grep -q "${EWS_IP}:22"; then
    /usr/sbin/sshd -o "ListenAddress=${EWS_IP}" -o "Port=22" || true
fi

echo "[setup_ssh] engineer user ready on ${EWS_IP}:22"
