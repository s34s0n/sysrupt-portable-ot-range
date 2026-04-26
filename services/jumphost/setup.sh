#!/bin/bash
# Configure the jumphost network namespace with SSH access
# Usage: sudo ./setup.sh
set -e

NS=ns-jumphost
VETH_HOST=veth-jh0
VETH_NS=veth-jh1
IP_ADDR=10.0.2.20/24
BRIDGE=br-dmz
USER=maintenance
PASS=maint2024!

echo "[+] Setting up Jump Host in namespace $NS"

# Create user if not exists
if ! id "$USER" &>/dev/null; then
    useradd -m -s /bin/bash "$USER"
    echo "$USER:$PASS" | chpasswd
    echo "[+] Created user $USER"
fi

# Copy bash_history
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cp "$SCRIPT_DIR/bash_history" /home/$USER/.bash_history
chown $USER:$USER /home/$USER/.bash_history

# Copy hosts file into namespace (if using ip netns exec)
cp "$SCRIPT_DIR/hosts" /home/$USER/hosts
echo "[+] Placed .bash_history and hosts in /home/$USER/"

# SSH config for namespace
mkdir -p /home/$USER/.ssh
chown -R $USER:$USER /home/$USER/.ssh

echo "[+] Jump Host setup complete"
echo "    SSH: ssh $USER@10.0.2.20 (password: $PASS)"
