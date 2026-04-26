#!/bin/bash
# Jumphost sshd - runs in foreground inside svc-jumphost namespace.
set -e

LISTEN_ADDR="10.0.2.20"
USER="maintenance"
PASS="maint2024!"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

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

# Plant bash_history breadcrumbs
if [ -f "$SCRIPT_DIR/bash_history" ]; then
    cp "$SCRIPT_DIR/bash_history" "/home/$USER/.bash_history"
    chown "$USER:$USER" "/home/$USER/.bash_history"
fi

# Copy hosts file
if [ -f "$SCRIPT_DIR/hosts" ]; then
    cp "$SCRIPT_DIR/hosts" "/home/$USER/hosts"
    chown "$USER:$USER" "/home/$USER/hosts"
fi

echo "[jumphost-sshd] Starting sshd on $LISTEN_ADDR:22"
exec /usr/sbin/sshd -D -e \
    -o "ListenAddress=$LISTEN_ADDR" \
    -o "Port=22" \
    -o "PasswordAuthentication=yes" \
    -o "UsePAM=yes"
