#!/bin/bash
# Sysrupt OT Range - Network namespace and bridge setup
# Idempotent: safe to run multiple times.
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
ENV_FILE="$PROJECT_ROOT/config/services/.env"
LOG_FILE="/var/log/ot-range-network.log"

if [ -f "$ENV_FILE" ]; then
    # shellcheck disable=SC1090
    set -a; . "$ENV_FILE"; set +a
fi

log() {
    local msg="$1"
    local ts
    ts="$(date '+%Y-%m-%d %H:%M:%S')"
    echo "[$ts] [setup] $msg"
    echo "[$ts] [setup] $msg" >> "$LOG_FILE" 2>/dev/null || true
}

if [ "$EUID" -ne 0 ]; then
    echo "[ERROR] setup-namespaces.sh must be run as root" >&2
    exit 1
fi

touch "$LOG_FILE" 2>/dev/null || true

log "=== Starting OT Range network setup ==="

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

create_bridge() {
    local name="$1"
    local ip_cidr="$2"

    if ip link show "$name" >/dev/null 2>&1; then
        log "bridge $name already exists, ensuring config"
    else
        log "creating bridge $name"
        ip link add name "$name" type bridge
    fi

    # Disable STP (ignore failures)
    ip link set "$name" type bridge stp_state 0 2>/dev/null || true

    # Assign IP if not already present
    if ip -4 addr show dev "$name" | grep -q "inet ${ip_cidr%/*}/"; then
        log "bridge $name already has ip $ip_cidr"
    else
        log "assigning $ip_cidr to $name"
        ip addr add "$ip_cidr" dev "$name" 2>/dev/null || true
    fi

    ip link set "$name" up
}

create_service_ns() {
    local ns="$1"
    local bridge="$2"
    local ip_cidr="$3"
    local gateway="$4"
    local short="$5"   # short suffix used for veth naming
    local vh="vh-${short}"
    local vp="vp-${short}"

    if ip netns list | awk '{print $1}' | grep -qx "$ns"; then
        log "namespace $ns already exists"
    else
        log "creating namespace $ns"
        ip netns add "$ns"
    fi

    # Create veth pair if host side doesn't exist already AND namespace doesn't already have veth0
    if ip link show "$vh" >/dev/null 2>&1; then
        log "host veth $vh already exists"
    elif ip netns exec "$ns" ip link show veth0 >/dev/null 2>&1; then
        log "veth0 already present inside $ns"
    else
        log "creating veth pair $vh <-> $vp (-> $ns:veth0)"
        ip link add "$vh" type veth peer name "$vp"
        ip link set "$vp" netns "$ns"
        ip netns exec "$ns" ip link set "$vp" name veth0
    fi

    # Attach host side to bridge
    local current_master
    current_master="$(ip -o link show "$vh" 2>/dev/null | grep -oE 'master [^ ]+' | awk '{print $2}' || true)"
    if [ "$current_master" = "$bridge" ]; then
        log "$vh already attached to $bridge"
    else
        log "attaching $vh to $bridge"
        ip link set "$vh" master "$bridge"
    fi
    ip link set "$vh" up

    # Bring up lo inside namespace
    ip netns exec "$ns" ip link set lo up

    # Assign IP inside namespace
    if ip netns exec "$ns" ip -4 addr show dev veth0 | grep -q "inet ${ip_cidr%/*}/"; then
        log "$ns veth0 already has ip $ip_cidr"
    else
        log "assigning $ip_cidr to $ns:veth0"
        ip netns exec "$ns" ip addr add "$ip_cidr" dev veth0 2>/dev/null || true
    fi

    ip netns exec "$ns" ip link set veth0 up

    # Default route inside namespace
    if ip netns exec "$ns" ip route show default | grep -q "via $gateway"; then
        log "$ns already has default route via $gateway"
    else
        log "setting default route via $gateway in $ns"
        ip netns exec "$ns" ip route replace default via "$gateway" dev veth0
    fi
}

# ---------------------------------------------------------------------------
# Step 1: IP forwarding
# ---------------------------------------------------------------------------
log "enabling ip forwarding"
sysctl -w net.ipv4.ip_forward=1 >/dev/null

# ---------------------------------------------------------------------------
# Step 2: bridges
# ---------------------------------------------------------------------------
create_bridge br-corp    10.0.1.1/24
create_bridge br-dmz     10.0.2.1/24
create_bridge br-scada   10.0.3.1/24
create_bridge br-process 10.0.4.1/24
create_bridge br-safety  10.0.5.1/24

# ---------------------------------------------------------------------------
# Step 3: eth0 to br-corp (optional)
# ---------------------------------------------------------------------------
if ip link show eth0 >/dev/null 2>&1; then
    eth0_master="$(ip -o link show eth0 | grep -oE 'master [^ ]+' | awk '{print $2}' || true)"
    if [ -z "$eth0_master" ]; then
        log "adding eth0 to br-corp"
        # Flush any IPs on eth0 first
        ip addr flush dev eth0 || true
        ip link set eth0 master br-corp
        ip link set eth0 up
    elif [ "$eth0_master" = "br-corp" ]; then
        log "eth0 already bridged to br-corp"
        ip link set eth0 up || true
    else
        log "eth0 is already attached to $eth0_master - leaving alone"
    fi
else
    log "eth0 not present, skipping bridge attachment"
fi

# ---------------------------------------------------------------------------
# Step 4: service namespaces
# ---------------------------------------------------------------------------
# Corp zone
create_service_ns svc-corp-web    br-corp    10.0.1.10/24 10.0.1.1 corp-web
create_service_ns svc-rtu-sensors br-corp    10.0.1.20/24 10.0.1.1 rtu-sn
create_service_ns svc-corp-mail   br-corp    10.0.1.30/24 10.0.1.1 corp-mail

# DMZ zone
create_service_ns svc-historian   br-dmz     10.0.2.10/24 10.0.2.1 histor
create_service_ns svc-jumphost    br-dmz     10.0.2.20/24 10.0.2.1 jump
create_service_ns svc-opcua       br-dmz     10.0.2.30/24 10.0.2.1 opcua

# SCADA zone
create_service_ns svc-scada-hmi   br-scada   10.0.3.10/24 10.0.3.1 scada-hmi
create_service_ns svc-eng-ws      br-scada   10.0.3.20/24 10.0.3.1 eng-ws
create_service_ns svc-ids         br-scada   10.0.3.30/24 10.0.3.1 ids

# Process zone
create_service_ns svc-plc-intake    br-process 10.0.4.101/24 10.0.4.1 plc-in
create_service_ns svc-plc-chemical  br-process 10.0.4.102/24 10.0.4.1 plc-ch
create_service_ns svc-plc-filter    br-process 10.0.4.103/24 10.0.4.1 plc-fi
create_service_ns svc-plc-distrib   br-process 10.0.4.104/24 10.0.4.1 plc-ds
create_service_ns svc-plc-power     br-process 10.0.4.105/24 10.0.4.1 plc-pw

# Safety zone
create_service_ns svc-safety-plc  br-safety  10.0.5.201/24 10.0.5.1 saf-plc
create_service_ns svc-safety-hmi  br-safety  10.0.5.202/24 10.0.5.1 saf-hmi

# ---------------------------------------------------------------------------
# Step 5: Dual-homing - SCADA and EWS secondary interfaces on process network
# ---------------------------------------------------------------------------

# SCADA secondary interface on process network
if ! ip netns exec svc-scada-hmi ip addr show dev veth-proc 2>/dev/null | grep -q "10.0.4.10"; then
    ip link add vh-scada-proc type veth peer name veth-proc
    ip link set vh-scada-proc master br-process
    ip link set vh-scada-proc up
    ip link set veth-proc netns svc-scada-hmi
    ip netns exec svc-scada-hmi ip addr add 10.0.4.10/24 dev veth-proc
    ip netns exec svc-scada-hmi ip link set veth-proc up
    log "SCADA dual-homed: added 10.0.4.10 on br-process"
fi

# EWS secondary interface on process network
if ! ip netns exec svc-eng-ws ip addr show dev veth-proc 2>/dev/null | grep -q "10.0.4.20"; then
    ip link add vh-ews-proc type veth peer name veth-proc
    ip link set vh-ews-proc master br-process
    ip link set vh-ews-proc up
    ip link set veth-proc netns svc-eng-ws
    ip netns exec svc-eng-ws ip addr add 10.0.4.20/24 dev veth-proc
    ip netns exec svc-eng-ws ip link set veth-proc up
    log "EWS dual-homed: added 10.0.4.20 on br-process"
fi

# EWS tertiary interface on safety network (forgotten maintenance bridge)
if ! ip netns exec svc-eng-ws ip addr show dev veth-safety 2>/dev/null | grep -q "10.0.5.20"; then
    ip link add vh-ews-safety type veth peer name veth-safety
    ip link set vh-ews-safety master br-safety
    ip link set vh-ews-safety up
    ip link set veth-safety netns svc-eng-ws
    ip netns exec svc-eng-ws ip addr add 10.0.5.20/24 dev veth-safety
    ip netns exec svc-eng-ws ip link set veth-safety up
    log "EWS triple-homed: added 10.0.5.20 on br-safety"
fi

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
log "=== Bridges ==="
ip -br link show type bridge | tee -a "$LOG_FILE" || true

log "=== Namespaces ==="
ip netns list | tee -a "$LOG_FILE" || true

log "=== Setup complete ==="

# ── Safety net: ensure ALL host-side veths are UP ──
log "Ensuring all host veths are UP"
for iface in $(ip -o link show | grep "vh-" | awk -F: "{print \$2}" | awk -F@ "{print \$1}" | tr -d " "); do
    ip link set "$iface" up 2>/dev/null && log "  $iface: UP" || true
done

# ── Copy dnsmasq config and restart AFTER bridges are up ──
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cp "$SCRIPT_DIR/dhcp/dnsmasq.conf" /etc/dnsmasq.d/ot-range.conf 2>/dev/null || true
log "Copied dnsmasq config and restarting"
systemctl --no-block restart dnsmasq 2>/dev/null || true
