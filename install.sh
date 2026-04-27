#!/bin/bash
# ==========================================================================
#  Sysrupt OT Range - Comprehensive Installer
#  Idempotent: safe to run multiple times.
# ==========================================================================
set -e

echo "╔═════════════════════════════════════╗"
echo "║     SYSRUPT OT RANGE INSTALLER      ║"
echo "║     v2.0 - ICS/SCADA Training Lab   ║"
echo "╚═════════════════════════════════════╝"
echo ""

# --------------------------------------------------------------------------
# Pre-flight
# --------------------------------------------------------------------------

if [ "$EUID" -ne 0 ]; then
    echo "[ERROR] Please run as root: sudo ./install.sh"
    exit 1
fi

if ! grep -q "Raspberry Pi" /proc/cpuinfo 2>/dev/null; then
    echo "[WARN] Not running on a Sysrupt board - some hardware features won't work"
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Determine the non-root user who owns the repo
INSTALL_USER="$(stat -c '%U' "$SCRIPT_DIR" 2>/dev/null || stat -f '%Su' "$SCRIPT_DIR" 2>/dev/null || echo sysrupt)"

# --------------------------------------------------------------------------
# Step 1: System packages
# --------------------------------------------------------------------------
echo "[1/14] Installing system packages..."
# DEBIAN_FRONTEND=noninteractive prevents debconf from hanging on prompts
# (notably iptables-persistent asks "save current rules?" which silently fails in -qq mode).
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq -o Dpkg::Options::='--force-confnew' \
    python3-pip python3-venv \
    redis-server \
    dnsmasq \
    iptables iptables-persistent \
    nmap \
    chromium-browser chromium \
    firefox \
    labwc kanshi swaybg unclutter \
    openssh-server \
    libsnap7-dev libsnap7-1 \
    device-tree-compiler \
    git build-essential cmake \
    || echo "[WARN] Some apt packages failed - continuing"

# Fall back to firefox-esr on distros without the rpt firefox package
if ! command -v firefox >/dev/null 2>&1; then
    apt-get install -y -qq firefox-esr || true
fi

# Sanity check: services that MUST exist for orchestrator to work
for cmd in iptables redis-server dnsmasq; do
    if ! command -v $cmd >/dev/null 2>&1; then
        echo "[ERROR] Required package missing: $cmd"
        echo "        Re-run: sudo DEBIAN_FRONTEND=noninteractive apt-get install -y $cmd"
        exit 1
    fi
done

# --------------------------------------------------------------------------
# Step 2: Python dependencies
# --------------------------------------------------------------------------
echo "[2/14] Installing Python dependencies..."
pip3 install --break-system-packages -r requirements.txt 2>/dev/null || \
    pip3 install --break-system-packages -r requirements.txt

# --------------------------------------------------------------------------
# Step 3: Configure Redis
# --------------------------------------------------------------------------
echo "[3/14] Configuring Redis..."
REDIS_CONF=/etc/redis/redis.conf
if [ -f "$REDIS_CONF" ]; then
    # Bind to all interfaces
    if grep -q "^bind 127.0.0.1" "$REDIS_CONF"; then
        sed -i 's/^bind 127.0.0.1.*/bind 0.0.0.0/' "$REDIS_CONF"
        echo "  Redis bind updated to 0.0.0.0"
    fi
    # Disable protected mode
    if grep -q "^protected-mode yes" "$REDIS_CONF"; then
        sed -i 's/^protected-mode yes/protected-mode no/' "$REDIS_CONF"
        echo "  Redis protected-mode disabled"
    fi
    systemctl enable redis-server 2>/dev/null || true
    systemctl restart redis-server 2>/dev/null || systemctl restart redis 2>/dev/null || true
    echo "  Redis enabled and restarted"
else
    echo "  [SKIP] Redis config not found at $REDIS_CONF"
fi

# --------------------------------------------------------------------------
# Step 4: Configure dnsmasq
# --------------------------------------------------------------------------
echo "[4/14] Configuring dnsmasq..."
# Ensure conf-dir is uncommented in /etc/dnsmasq.conf
if [ -f /etc/dnsmasq.conf ]; then
    if grep -q "^#conf-dir=/etc/dnsmasq.d" /etc/dnsmasq.conf; then
        sed -i 's|^#conf-dir=/etc/dnsmasq.d$|conf-dir=/etc/dnsmasq.d|' /etc/dnsmasq.conf
        echo "  Uncommented conf-dir=/etc/dnsmasq.d in /etc/dnsmasq.conf"
    fi
fi
mkdir -p /etc/dnsmasq.d
if [ -f "$SCRIPT_DIR/config/network/dhcp/dnsmasq.conf" ]; then
    cp "$SCRIPT_DIR/config/network/dhcp/dnsmasq.conf" /etc/dnsmasq.d/ot-range.conf
    echo "  Copied dnsmasq config to /etc/dnsmasq.d/ot-range.conf"
fi
systemctl enable dnsmasq 2>/dev/null || true
echo "  dnsmasq enabled"

# --------------------------------------------------------------------------
# Step 5: Configure NetworkManager
# --------------------------------------------------------------------------
echo "[5/14] Configuring NetworkManager..."
mkdir -p /etc/NetworkManager/conf.d
cat > /etc/NetworkManager/conf.d/ot-range-unmanaged.conf << NMEOF
[keyfile]
unmanaged-devices=interface-name:eth0;interface-name:br-*;interface-name:vh-*
NMEOF
nmcli general reload 2>/dev/null || true
echo "  NetworkManager configured"

# --------------------------------------------------------------------------
# Step 6: Display overlay
# --------------------------------------------------------------------------
echo "[6/14] Installing display overlay..."
OVERLAY_DIR="$SCRIPT_DIR/hardware/display-overlay"
if [ -f "$OVERLAY_DIR/sysrupt-ili9341-spi1.dtbo" ]; then
    BOOT_OVL=""
    if [ -d /boot/firmware/overlays ]; then
        BOOT_OVL=/boot/firmware/overlays
    elif [ -d /boot/overlays ]; then
        BOOT_OVL=/boot/overlays
    fi
    if [ -n "$BOOT_OVL" ]; then
        cp "$OVERLAY_DIR/sysrupt-ili9341-spi1.dtbo" "$BOOT_OVL/"
        echo "  Overlay installed to $BOOT_OVL/"
    fi

    # Ensure config.txt has the overlay line
    CONFIG_TXT=""
    if [ -f /boot/firmware/config.txt ]; then
        CONFIG_TXT=/boot/firmware/config.txt
    elif [ -f /boot/config.txt ]; then
        CONFIG_TXT=/boot/config.txt
    fi
    if [ -n "$CONFIG_TXT" ]; then
        grep -q "dtoverlay=sysrupt-ili9341-spi1" "$CONFIG_TXT" 2>/dev/null || \
            echo "dtoverlay=sysrupt-ili9341-spi1" >> "$CONFIG_TXT"
        grep -q "max_framebuffers=2" "$CONFIG_TXT" 2>/dev/null || \
            echo "max_framebuffers=2" >> "$CONFIG_TXT"
        echo "  config.txt updated ($CONFIG_TXT)"
    fi
else
    echo "  [SKIP] No overlay DTBO found in $OVERLAY_DIR"
fi

# --------------------------------------------------------------------------
# Step 7: Enable SPI and I2C
# --------------------------------------------------------------------------
echo "[7/14] Enabling SPI and I2C..."
raspi-config nonint do_spi 0 2>/dev/null || echo "  [SKIP] SBC config tool not available"
raspi-config nonint do_i2c 0 2>/dev/null || echo "  [SKIP] SBC config tool not available"

# --------------------------------------------------------------------------
# Step 8: labwc kiosk config
# --------------------------------------------------------------------------
echo "[8/14] Configuring display kiosk..."
LABWC_DIR="/home/$INSTALL_USER/.config/labwc"
mkdir -p "$LABWC_DIR"
cp "$SCRIPT_DIR/hardware/display-overlay/labwc-autostart" "$LABWC_DIR/autostart" 2>/dev/null || true
cp "$SCRIPT_DIR/hardware/display-overlay/labwc-environment" "$LABWC_DIR/environment" 2>/dev/null || true
if [ -f "$SCRIPT_DIR/hardware/display-overlay/labwc-rc.xml" ]; then
    cp "$SCRIPT_DIR/hardware/display-overlay/labwc-rc.xml" "$LABWC_DIR/rc.xml"
fi
chown -R "$INSTALL_USER:$INSTALL_USER" "$LABWC_DIR"
echo "  labwc config installed for $INSTALL_USER"

# --------------------------------------------------------------------------
# Step 9: Network namespaces and firewall
# --------------------------------------------------------------------------
echo "[9/14] Setting up network namespaces and firewall..."
bash "$SCRIPT_DIR/config/network/setup-namespaces.sh"
bash "$SCRIPT_DIR/config/network/firewall-rules.sh"

# --------------------------------------------------------------------------
# Step 10: Users
# --------------------------------------------------------------------------
echo "[10/14] Creating lab users..."
if ! id maintenance >/dev/null 2>&1; then
    useradd -m -s /bin/bash maintenance
    echo "maintenance:maint2024!" | chpasswd
    echo "  Created user: maintenance"
else
    echo "  User maintenance already exists"
fi
if ! id engineer >/dev/null 2>&1; then
    useradd -m -s /bin/bash engineer
    echo "engineer:eng2024!" | chpasswd
    echo "  Created user: engineer"
else
    echo "  User engineer already exists"
fi

# Add PYTHONPATH to lab user profiles (needed for c104, snap7, etc. via SSH)
USER_HOME="$(eval echo ~$INSTALL_USER)"
SITE_PKGS="$(sudo -u "$INSTALL_USER" python3 -c 'import site; print(site.USER_SITE)' 2>/dev/null || echo "$USER_HOME/.local/lib/python3/site-packages")"
PYPATH_LINE="export PYTHONPATH=$SITE_PKGS:$SCRIPT_DIR"
for u in engineer maintenance; do
    BASHRC="/home/$u/.bashrc"
    if [ -f "$BASHRC" ]; then
        grep -q 'PYTHONPATH.*sysrupt' "$BASHRC" 2>/dev/null || echo "$PYPATH_LINE" >> "$BASHRC"
    fi
done
echo "  PYTHONPATH configured for engineer and maintenance users"

# --------------------------------------------------------------------------
# Step 11: SSH host keys
# --------------------------------------------------------------------------
echo "[11/14] Generating SSH host keys..."
ssh-keygen -A 2>/dev/null || true
echo "  SSH host keys ensured"

# --------------------------------------------------------------------------
# Step 12: Log and run directories
# --------------------------------------------------------------------------
echo "[12/14] Creating log and run directories..."
mkdir -p /var/log/ot-range /var/run/ot-range
chown -R "$INSTALL_USER:$INSTALL_USER" /var/log/ot-range /var/run/ot-range
echo "  Directories created, owned by $INSTALL_USER"

# --------------------------------------------------------------------------
# Step 13: Systemd services
# --------------------------------------------------------------------------
echo "[13/14] Installing systemd services..."

# Detect the actual python3 site-packages path for the install user (varies by Python version)
USER_HOME="$(eval echo ~$INSTALL_USER)"
PY_SITE="$(sudo -u "$INSTALL_USER" python3 -c 'import site; print(site.USER_SITE)' 2>/dev/null || echo "$USER_HOME/.local/lib/python3/site-packages")"

# Network service - rewrite paths from repo template to actual install location
sed -e "s|/home/sysrupt/sysrupt-ot-range|$SCRIPT_DIR|g" \
    "$SCRIPT_DIR/config/network/ot-range-network.service" \
    > /etc/systemd/system/ot-range-network.service
echo "  Installed ot-range-network.service (paths -> $SCRIPT_DIR)"

# Main orchestrator service - templated with actual paths
cat > /etc/systemd/system/ot-range.service << SVCEOF
[Unit]
Description=Sysrupt OT Range Orchestrator
After=ot-range-network.service redis-server.service
Requires=ot-range-network.service
Wants=redis-server.service

[Service]
Type=oneshot
RemainAfterExit=yes
TimeoutStartSec=300
WorkingDirectory=$SCRIPT_DIR
Environment=PYTHONPATH=$PY_SITE:$SCRIPT_DIR
ExecStart=/usr/bin/python3 -m orchestrator start
ExecStop=/usr/bin/python3 -m orchestrator stop
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
SVCEOF
echo "  Installed ot-range.service (paths -> $SCRIPT_DIR)"

systemctl daemon-reload
systemctl enable ot-range-network.service 2>/dev/null || true
systemctl enable ot-range.service 2>/dev/null || true
echo "  Services enabled"

# --------------------------------------------------------------------------
# Step 14: Executable permissions + health check
# --------------------------------------------------------------------------
echo "[14/14] Setting executable permissions and running health check..."
find "$SCRIPT_DIR" -name "*.sh" -exec chmod +x {} \;
chmod +x "$SCRIPT_DIR/display/launcher.sh" 2>/dev/null || true
echo "  All .sh files set executable"

# Health check
echo ""
echo "--- Health Check ---"

if redis-cli ping 2>/dev/null | grep -q PONG; then
    echo "  [OK] Redis is responding"
else
    echo "  [WARN] Redis not responding"
fi

for br in br-corp br-dmz br-scada br-process br-safety; do
    if ip link show "$br" >/dev/null 2>&1; then
        echo "  [OK] Bridge $br exists"
    else
        echo "  [WARN] Bridge $br not found"
    fi
done

NS_COUNT=$(ip netns list 2>/dev/null | wc -l)
echo "  [OK] $NS_COUNT network namespaces configured"

echo ""
echo "╔═════════════════════════════════════╗"
echo "║     INSTALLATION COMPLETE            ║"
echo "║                                      ║"
echo "║  Start:   sudo python3 -m orchestrator start  ║"
echo "║  Status:  sudo python3 -m orchestrator status  ║"
echo "║  Reboot to activate display overlay  ║"
echo "╚═════════════════════════════════════╝"
