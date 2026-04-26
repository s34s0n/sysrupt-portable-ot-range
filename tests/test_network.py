"""
Sysrupt OT Range - Network infrastructure tests.

Run with:  sudo pytest tests/test_network.py -v

These tests verify the state produced by:
    config/network/setup-namespaces.sh
    config/network/firewall-rules.sh

If the setup has not been run, tests are skipped cleanly.
"""
import os
import subprocess

import pytest


BRIDGES = {
    "br-corp": "10.0.1.1",
    "br-dmz": "10.0.2.1",
    "br-scada": "10.0.3.1",
    "br-process": "10.0.4.1",
    "br-safety": "10.0.5.1",
}

SERVICES = {
    "svc-corp-web":     ("br-corp",    "10.0.1.10",  "10.0.1.1"),
    "svc-rtu-sensors":  ("br-corp",    "10.0.1.20",  "10.0.1.1"),
    "svc-corp-mail":    ("br-corp",    "10.0.1.30",  "10.0.1.1"),
    "svc-historian":    ("br-dmz",     "10.0.2.10",  "10.0.2.1"),
    "svc-jumphost":     ("br-dmz",     "10.0.2.20",  "10.0.2.1"),
    "svc-opcua":        ("br-dmz",     "10.0.2.30",  "10.0.2.1"),
    "svc-scada-hmi":    ("br-scada",   "10.0.3.10",  "10.0.3.1"),
    "svc-eng-ws":       ("br-scada",   "10.0.3.20",  "10.0.3.1"),
    "svc-ids":          ("br-scada",   "10.0.3.30",  "10.0.3.1"),
    "svc-plc-intake":   ("br-process", "10.0.4.101", "10.0.4.1"),
    "svc-plc-chemical": ("br-process", "10.0.4.102", "10.0.4.1"),
    "svc-plc-filter":   ("br-process", "10.0.4.103", "10.0.4.1"),
    "svc-plc-distrib":  ("br-process", "10.0.4.104", "10.0.4.1"),
    "svc-plc-power":    ("br-process", "10.0.4.105", "10.0.4.1"),
    "svc-safety-plc":   ("br-safety",  "10.0.5.201", "10.0.5.1"),
    "svc-safety-hmi":   ("br-safety",  "10.0.5.202", "10.0.5.1"),
}


def run(cmd, check=False):
    """Run a command and return CompletedProcess."""
    if isinstance(cmd, str):
        cmd = cmd.split()
    return subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=check,
    )


@pytest.fixture(autouse=True)
def _require_root():
    if os.geteuid() != 0:
        pytest.skip("network tests require root (run with sudo)")


@pytest.fixture(scope="module", autouse=True)
def _require_setup():
    """Skip the whole module if setup has not been run."""
    r = run("ip link show br-corp")
    if r.returncode != 0:
        pytest.skip(
            "OT Range network not configured - run "
            "sudo bash config/network/setup-namespaces.sh first"
        )


# ---------------------------------------------------------------------------
# Original tests
# ---------------------------------------------------------------------------

def test_bridges_exist():
    for br in BRIDGES:
        r = run(f"ip link show {br}")
        assert r.returncode == 0, f"bridge {br} missing: {r.stderr}"


def test_bridge_ips():
    for br, ip in BRIDGES.items():
        r = run(f"ip -4 addr show dev {br}")
        assert r.returncode == 0
        assert f"inet {ip}/" in r.stdout, (
            f"bridge {br} missing ip {ip}: {r.stdout}"
        )


def test_service_namespaces_exist():
    r = run("ip netns list")
    assert r.returncode == 0
    existing = {line.split()[0] for line in r.stdout.strip().splitlines() if line.strip()}
    for ns in SERVICES:
        assert ns in existing, f"namespace {ns} missing (have {existing})"


def test_service_ips_reachable():
    for ns, (_, ip, _) in SERVICES.items():
        r = run(f"ping -c 1 -W 2 {ip}")
        assert r.returncode == 0, (
            f"{ns} at {ip} not reachable from default ns: {r.stdout} {r.stderr}"
        )


def test_ip_forwarding_enabled():
    with open("/proc/sys/net/ipv4/ip_forward") as f:
        assert f.read().strip() == "1", "ip_forward not enabled"


def test_corp_cannot_reach_process_directly():
    """Corp zone must not be able to ping a process-zone PLC."""
    r = run("ip netns exec svc-corp-web ping -c 1 -W 2 10.0.4.101")
    assert r.returncode != 0, (
        "corp -> process ping succeeded (should be dropped by firewall)"
    )


def test_corp_can_reach_dmz_ssh_path():
    """Routing path from corp to DMZ should be in place."""
    r = run("ip netns exec svc-corp-web ip route get 10.0.2.10")
    assert r.returncode == 0, f"no route from corp to dmz: {r.stderr}"
    assert "via 10.0.1.1" in r.stdout, (
        f"corp ns does not route via br-corp gateway: {r.stdout}"
    )


def test_iptables_default_drop():
    r = run("iptables -L FORWARD -n")
    assert r.returncode == 0
    first_line = r.stdout.splitlines()[0]
    assert "policy DROP" in first_line, (
        f"FORWARD default policy is not DROP: {first_line}"
    )
    r = run("iptables -L OT-RANGE-FORWARD -n")
    assert r.returncode == 0, "OT-RANGE-FORWARD chain missing"
    lines = [l for l in r.stdout.splitlines() if l.strip()]
    assert any(l.startswith("DROP") for l in lines), (
        f"OT-RANGE-FORWARD has no DROP rule: {r.stdout}"
    )


def test_veth_pairs_exist():
    """Every service namespace should have a veth0."""
    for ns in SERVICES:
        r = run(f"ip netns exec {ns} ip link show veth0")
        assert r.returncode == 0, f"{ns} is missing veth0"

    # At least enough vh-* interfaces on the host
    r = run("ip -o link show")
    assert r.returncode == 0
    vh_count = sum(1 for line in r.stdout.splitlines() if ": vh-" in line)
    # We have SERVICES count + 3 extra (vh-scada-proc, vh-ews-proc, vh-ews-safety)
    assert vh_count >= len(SERVICES), (
        f"expected at least {len(SERVICES)} vh-* interfaces, found {vh_count}"
    )


def test_namespace_default_routes():
    for ns, (_, _, gw) in SERVICES.items():
        r = run(f"ip netns exec {ns} ip route show default")
        assert r.returncode == 0
        assert f"via {gw}" in r.stdout, (
            f"{ns} default route wrong: {r.stdout}"
        )


# ---------------------------------------------------------------------------
# New tests: Purdue model architecture validation
# ---------------------------------------------------------------------------

def test_bacnet_on_corp_network():
    """BACnet BMS must be on corporate network (10.0.1.20), not process."""
    r = run("ip netns exec svc-rtu-sensors ip -4 addr show dev veth0")
    assert r.returncode == 0
    assert "10.0.1.20" in r.stdout, (
        f"BMS should be at 10.0.1.20 on corp, got: {r.stdout}"
    )
    assert "10.0.4" not in r.stdout, (
        "BMS should NOT be on process network"
    )


def test_scada_dual_homed():
    """SCADA HMI must have interfaces on both br-scada and br-process."""
    r = run("ip netns exec svc-scada-hmi ip -4 addr")
    assert r.returncode == 0
    assert "10.0.3.10" in r.stdout, "SCADA missing primary 10.0.3.10"
    assert "10.0.4.10" in r.stdout, "SCADA missing secondary 10.0.4.10"


def test_ews_triple_homed():
    """EWS must have interfaces on br-scada, br-process, and br-safety."""
    r = run("ip netns exec svc-eng-ws ip -4 addr")
    assert r.returncode == 0
    assert "10.0.3.20" in r.stdout, "EWS missing 10.0.3.20 (scada)"
    assert "10.0.4.20" in r.stdout, "EWS missing 10.0.4.20 (process)"
    assert "10.0.5.20" in r.stdout, "EWS missing 10.0.5.20 (safety)"


def test_corp_cannot_reach_safety():
    """Corporate zone must NOT reach safety zone."""
    r = run("ip netns exec svc-corp-web ping -c 1 -W 2 10.0.5.201")
    assert r.returncode != 0, (
        "corp -> safety ping succeeded (should be dropped)"
    )


def test_dmz_cannot_reach_process():
    """DMZ must NOT directly reach process zone."""
    r = run("ip netns exec svc-historian ping -c 1 -W 2 10.0.4.101")
    assert r.returncode != 0, (
        "dmz -> process ping succeeded (should be dropped)"
    )


def test_no_direct_route_to_safety():
    """No ACCEPT rules for 10.0.5.x in the FORWARD chain."""
    r = run("iptables -L OT-RANGE-FORWARD -n")
    assert r.returncode == 0
    for line in r.stdout.splitlines():
        if line.startswith("ACCEPT"):
            assert "10.0.5" not in line, (
                f"Found ACCEPT rule targeting safety zone: {line}"
            )


def test_ews_can_reach_process():
    """EWS dual-homed interface can reach process PLCs."""
    r = run("ip netns exec svc-eng-ws ping -c 1 -W 2 10.0.4.101")
    assert r.returncode == 0, (
        "ews -> process ping failed (should succeed via dual-homed interface)"
    )


def test_ews_can_reach_safety():
    """EWS triple-homed interface can reach safety PLC."""
    r = run("ip netns exec svc-eng-ws ping -c 1 -W 2 10.0.5.201")
    assert r.returncode == 0, (
        "ews -> safety ping failed (should succeed via triple-homed interface)"
    )
