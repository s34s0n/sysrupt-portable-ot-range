#!/bin/bash
# Engineering Workstation sshd - runs in foreground inside svc-eng-ws namespace.
set -e

LISTEN_ADDR="10.0.3.20"
USER="engineer"
PASS="eng2024!"

# Wait for namespace IP to be ready
for i in $(seq 1 10); do
    if ip addr show | grep -q "$LISTEN_ADDR"; then
        break
    fi
    sleep 0.5
done

# Generate SSH host keys if missing
ssh-keygen -A 2>/dev/null || true

# Create /var/run/sshd (required by sshd)
mkdir -p /var/run/sshd

# Create user if not exists
if ! id "$USER" >/dev/null 2>&1; then
    useradd -m -s /bin/bash "$USER"
    echo "$USER:$PASS" | chpasswd
fi

# /etc/hosts breadcrumbs
if ! grep -q "plc-intake" /etc/hosts 2>/dev/null; then
    cat >> /etc/hosts << 'HOSTS'
# OT plant hosts
10.0.4.101   plc-intake
10.0.4.102   plc-chemical
10.0.4.103   plc-filtration
10.0.4.104   plc-distribution
10.0.4.105   plc-power
10.0.3.10    scada-hmi
10.0.2.10    historian
10.0.2.30    opcua-gw
HOSTS
fi

# Plant recon commands in bash_history
cat > "/home/$USER/.bash_history" << 'EOF'
ping -c2 plc-intake
ss -tlnp
nmap -sV 10.0.4.101 -p 502
python3 -c "from pymodbus.client import ModbusTcpClient; c=ModbusTcpClient('10.0.4.101'); c.connect(); print(c.read_holding_registers(0,10))"
curl http://scada-hmi:8080/api/status
cat /etc/hosts
ip addr
EOF
chown "$USER:$USER" "/home/$USER/.bash_history"

echo "[ews-sshd] Starting sshd on $LISTEN_ADDR:22"
exec /usr/sbin/sshd -D -e \
    -o "ListenAddress=$LISTEN_ADDR" \
    -o "Port=22" \
    -o "PasswordAuthentication=yes" \
    -o "UsePAM=yes"
