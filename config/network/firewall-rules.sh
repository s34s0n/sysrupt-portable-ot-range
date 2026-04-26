#!/bin/bash
# Sysrupt OT Range - Firewall rules
# Idempotent: flushes the OT-RANGE-FORWARD chain on each run and rebuilds.
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
ENV_FILE="$PROJECT_ROOT/config/services/.env"
LOG_FILE="/var/log/ot-range-network.log"
CHAIN="OT-RANGE-FORWARD"

if [ -f "$ENV_FILE" ]; then
    # shellcheck disable=SC1090
    set -a; . "$ENV_FILE"; set +a
fi

log() {
    local msg="$1"
    local ts
    ts="$(date '+%Y-%m-%d %H:%M:%S')"
    echo "[$ts] [fw] $msg"
    echo "[$ts] [fw] $msg" >> "$LOG_FILE" 2>/dev/null || true
}

if [ "$EUID" -ne 0 ]; then
    echo "[ERROR] firewall-rules.sh must be run as root" >&2
    exit 1
fi

touch "$LOG_FILE" 2>/dev/null || true

log "=== Starting firewall rules setup ==="

CORP_NET=10.0.1.0/24
DMZ_NET=10.0.2.0/24
SCADA_NET=10.0.3.0/24
PROCESS_NET=10.0.4.0/24
SAFETY_NET=10.0.5.0/24

OPCUA_IP=10.0.2.30
PLC_FILTER_IP=10.0.4.103
PLC_DISTRIB_IP=10.0.4.104
PLC_POWER_IP=10.0.4.105

# ---------------------------------------------------------------------------
# FORWARD default policy DROP
# ---------------------------------------------------------------------------
log "setting FORWARD default policy DROP"
iptables -P FORWARD DROP

# ---------------------------------------------------------------------------
# Chain setup
# ---------------------------------------------------------------------------
if iptables -L "$CHAIN" -n >/dev/null 2>&1; then
    log "flushing existing $CHAIN chain"
    iptables -F "$CHAIN"
else
    log "creating $CHAIN chain"
    iptables -N "$CHAIN"
fi

# Ensure FORWARD jumps to our chain (only once)
if iptables -C FORWARD -j "$CHAIN" 2>/dev/null; then
    log "FORWARD jump to $CHAIN already present"
else
    log "inserting FORWARD jump to $CHAIN"
    iptables -I FORWARD 1 -j "$CHAIN"
fi

# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------

log "allowing established/related"
iptables -A "$CHAIN" -m state --state ESTABLISHED,RELATED -j ACCEPT

# Corp -> DMZ
log "Corp -> DMZ: 443, 8443, 22"
iptables -A "$CHAIN" -s "$CORP_NET" -d "$DMZ_NET" -p tcp -m multiport --dports 22,443,8080,8443 -j ACCEPT
log "Corp -> DMZ opcua-gateway: 4840 only to $OPCUA_IP"
iptables -A "$CHAIN" -s "$CORP_NET" -d "$OPCUA_IP" -p tcp --dport 4840 -j ACCEPT

# DMZ -> SCADA
log "DMZ -> SCADA: 8080, 22, 4840"
iptables -A "$CHAIN" -s "$DMZ_NET" -d "$SCADA_NET" -p tcp -m multiport --dports 22,4840,8080 -j ACCEPT

# SCADA -> Process
log "SCADA -> Process: 502 (modbus)"
iptables -A "$CHAIN" -s "$SCADA_NET" -d "$PROCESS_NET" -p tcp --dport 502 -j ACCEPT
log "SCADA -> plc-filter: 20000 (dnp3)"
iptables -A "$CHAIN" -s "$SCADA_NET" -d "$PLC_FILTER_IP" -p tcp --dport 20000 -j ACCEPT
log "SCADA -> plc-distrib: 44818 (enip tcp)"
iptables -A "$CHAIN" -s "$SCADA_NET" -d "$PLC_DISTRIB_IP" -p tcp --dport 44818 -j ACCEPT
log "SCADA -> plc-distrib: 44818/udp (enip listidentity)"
iptables -A "$CHAIN" -s "$SCADA_NET" -d "$PLC_DISTRIB_IP" -p udp --dport 44818 -j ACCEPT
log "SCADA -> plc-power: 2404 (iec 60870-5-104)"
iptables -A "$CHAIN" -s "$SCADA_NET" -d "$PLC_POWER_IP" -p tcp --dport 2404 -j ACCEPT

# ---------------------------------------------------------------------------
# Block student DHCP range from host services (Redis, Display)
# ---------------------------------------------------------------------------
# Block entire corp subnet from Redis (students and services on br-corp)
# Corp-web CTF triggers are set by the test harness / CTF engine directly.
log "blocking corp subnet from Redis port 6379"
iptables -A INPUT -p tcp --dport 6379 -m iprange --src-range 10.0.1.50-10.0.1.200 -j DROP

# Block corp subnet from display server port 5555
log "blocking corp subnet from display port 5555"
iptables -A INPUT -p tcp --dport 5555 -m iprange --src-range 10.0.1.50-10.0.1.200 -j DROP

# Block entire DMZ subnet from Redis (no DMZ service needs Redis)

# ---------------------------------------------------------------------------
# Host self rules: do NOT break management access
# ---------------------------------------------------------------------------
log "Host self: accept SSH on wlan0"
if iptables -C INPUT -i wlan0 -p tcp --dport 22 -j ACCEPT 2>/dev/null; then
    :
else
    iptables -I INPUT 1 -i wlan0 -p tcp --dport 22 -j ACCEPT
fi

log "Host self: accept SSH on br-corp"
if iptables -C INPUT -i br-corp -p tcp --dport 22 -j ACCEPT 2>/dev/null; then
    :
else
    iptables -I INPUT 1 -i br-corp -p tcp --dport 22 -j ACCEPT
fi

# ---------------------------------------------------------------------------
# Logging drop + final drop
# ---------------------------------------------------------------------------
log "adding rate-limited LOG rule for drops"
iptables -A "$CHAIN" -m limit --limit 5/minute -j LOG --log-prefix "OT-RANGE-DROP: " --log-level 4
iptables -A "$CHAIN" -j DROP

log "=== Firewall rules setup complete ==="
