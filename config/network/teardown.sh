#!/bin/bash
# Sysrupt OT Range - Teardown
# Idempotent: safe to run even if nothing is set up.
set +e

LOG_FILE="/var/log/ot-range-network.log"
CHAIN="OT-RANGE-FORWARD"

log() {
    local msg="$1"
    local ts
    ts="$(date '+%Y-%m-%d %H:%M:%S')"
    echo "[$ts] [teardown] $msg"
    echo "[$ts] [teardown] $msg" >> "$LOG_FILE" 2>/dev/null || true
}

if [ "$EUID" -ne 0 ]; then
    echo "[ERROR] teardown.sh must be run as root" >&2
    exit 1
fi

touch "$LOG_FILE" 2>/dev/null || true

log "=== Starting teardown ==="

# ---------------------------------------------------------------------------
# 1. Stop dnsmasq
# ---------------------------------------------------------------------------
log "stopping dnsmasq"
systemctl stop dnsmasq 2>/dev/null || true

# ---------------------------------------------------------------------------
# 2. Remove drop-in config
# ---------------------------------------------------------------------------
if [ -f /etc/dnsmasq.d/ot-range.conf ]; then
    log "removing /etc/dnsmasq.d/ot-range.conf"
    rm -f /etc/dnsmasq.d/ot-range.conf
fi

# ---------------------------------------------------------------------------
# 3/4. Remove FORWARD jump and flush/delete OT-RANGE-FORWARD chain
# ---------------------------------------------------------------------------
if iptables -C FORWARD -j "$CHAIN" 2>/dev/null; then
    log "removing FORWARD jump to $CHAIN"
    while iptables -C FORWARD -j "$CHAIN" 2>/dev/null; do
        iptables -D FORWARD -j "$CHAIN"
    done
fi

if iptables -L "$CHAIN" -n >/dev/null 2>&1; then
    log "flushing and deleting $CHAIN chain"
    iptables -F "$CHAIN" 2>/dev/null || true
    iptables -X "$CHAIN" 2>/dev/null || true
fi

# Also clean up the INPUT rules we added (SSH accept on br-corp is safe to leave,
# but remove for cleanliness). We leave wlan0 SSH accept alone to avoid surprises.
while iptables -C INPUT -i br-corp -p tcp --dport 22 -j ACCEPT 2>/dev/null; do
    log "removing INPUT accept on br-corp"
    iptables -D INPUT -i br-corp -p tcp --dport 22 -j ACCEPT
done

# ---------------------------------------------------------------------------
# 5. Remove eth0 from br-corp
# ---------------------------------------------------------------------------
if ip link show eth0 >/dev/null 2>&1; then
    eth0_master="$(ip -o link show eth0 | grep -oE 'master [^ ]+' | awk '{print $2}' || true)"
    if [ "$eth0_master" = "br-corp" ]; then
        log "removing eth0 from br-corp"
        ip link set eth0 nomaster 2>/dev/null || true
        ip link set eth0 up 2>/dev/null || true
    fi
fi

# ---------------------------------------------------------------------------
# 6. Delete service namespaces
# ---------------------------------------------------------------------------
NAMESPACES=(
    svc-corp-web svc-corp-mail
    svc-historian svc-jumphost svc-opcua
    svc-scada-hmi svc-eng-ws svc-ids
    svc-plc-intake svc-plc-chemical svc-plc-filter svc-plc-distrib svc-plc-power svc-rtu-sensors
    svc-safety-plc svc-safety-hmi
)
for ns in "${NAMESPACES[@]}"; do
    if ip netns list | awk '{print $1}' | grep -qx "$ns"; then
        log "deleting namespace $ns"
        ip netns del "$ns" 2>/dev/null || true
    fi
done

# Clean up any stray host-side veths (vh-*)
for vh in $(ip -o link show 2>/dev/null | awk -F': ' '{print $2}' | awk '{print $1}' | sed 's/@.*//' | grep '^vh-' || true); do
    log "deleting stray veth $vh"
    ip link del "$vh" 2>/dev/null || true
done

# ---------------------------------------------------------------------------
# 7. Delete bridges
# ---------------------------------------------------------------------------
for br in br-corp br-dmz br-scada br-process br-safety; do
    if ip link show "$br" >/dev/null 2>&1; then
        log "deleting bridge $br"
        ip link set "$br" down 2>/dev/null || true
        ip link del "$br" 2>/dev/null || true
    fi
done

# ---------------------------------------------------------------------------
# 8. Disable IP forwarding
# ---------------------------------------------------------------------------
log "disabling ip forwarding"
sysctl -w net.ipv4.ip_forward=0 >/dev/null 2>&1 || true

log "=== Teardown complete ==="
exit 0
