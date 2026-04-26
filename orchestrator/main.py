"""Orchestrator - single-command start/stop/reset for the OT Range."""

import json
import logging
import os
import signal
import socket
import subprocess
import sys
import time
from typing import Dict, List, Optional, Any

import redis

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PYPATH = "/home/sysrupt/.local/lib/python3.13/site-packages"
PROJECT_DIR = "/home/sysrupt/sysrupt-ot-range"
PID_DIR = "/var/run/ot-range"
PID_FILE = os.path.join(PID_DIR, "pids.json")
LOG_DIR = "/var/log/ot-range"

log = logging.getLogger("orchestrator")

# ---------------------------------------------------------------------------
# Service definition
# ---------------------------------------------------------------------------

class ServiceDef:
    """Single service definition."""

    def __init__(
        self,
        name: str,
        phase: int,
        svc_type: str,
        command: str,
        namespace: Optional[str] = None,
        health_check: Optional[str] = None,
        health_target: Optional[str] = None,
        env: Optional[Dict[str, str]] = None,
        cwd: Optional[str] = None,
        user: Optional[str] = None,
    ):
        self.name = name
        self.phase = phase
        self.svc_type = svc_type          # setup | daemon | systemd
        self.command = command
        self.namespace = namespace
        self.health_check = health_check  # tcp_port | redis_ping | redis_key | process | bridge_exists | http | systemd
        self.health_target = health_target
        self.env = env or {}
        self.cwd = cwd or PROJECT_DIR
        self.user = user


# 22 services across 10 phases
SERVICES: List[ServiceDef] = [
    # --- Phase 1: Network ---
    ServiceDef(
        name="setup-namespaces",
        phase=1,
        svc_type="setup",
        command=f"bash {PROJECT_DIR}/config/network/setup-namespaces.sh",
        health_check="bridge_exists",
        health_target="br-corp",
    ),
    ServiceDef(
        name="firewall-rules",
        phase=1,
        svc_type="setup",
        command=f"bash {PROJECT_DIR}/config/network/firewall-rules.sh",
        health_check="bridge_exists",
        health_target="br-scada",
    ),
    # --- Phase 2: Redis ---
    ServiceDef(
        name="redis",
        phase=2,
        svc_type="systemd",
        command="redis-server",
        health_check="redis_ping",
        health_target="127.0.0.1:6379",
    ),
    # --- Phase 3: Hardware manager ---
    ServiceDef(
        name="hardware-manager",
        phase=3,
        svc_type="daemon",
        command=f"python3 -m hardware.manager_daemon",
        health_check="redis_key",
        health_target="hw:mode",
    ),
    # --- Phase 4: PLCs ---
    ServiceDef(
        name="plc-intake",
        phase=4,
        svc_type="daemon",
        command=f"python3 {PROJECT_DIR}/services/plc-intake/server.py",
        namespace="svc-plc-intake",
        health_check="tcp_port",
        health_target="10.0.4.101:502",
    ),
    ServiceDef(
        name="plc-chemical",
        phase=4,
        svc_type="daemon",
        command=f"python3 {PROJECT_DIR}/services/plc-chemical/server.py",
        namespace="svc-plc-chemical",
        health_check="tcp_port",
        health_target="10.0.4.102:502",
    ),
    ServiceDef(
        name="plc-filtration",
        phase=4,
        svc_type="daemon",
        command=f"python3 {PROJECT_DIR}/services/plc-filtration/server.py",
        namespace="svc-plc-filter",
        health_check="tcp_port",
        health_target="10.0.4.103:20000",
    ),
    ServiceDef(
        name="plc-distribution",
        phase=4,
        svc_type="daemon",
        command=f"python3 {PROJECT_DIR}/services/plc-distribution/server.py",
        namespace="svc-plc-distrib",
        health_check="redis_key",
        health_target="plc:distribution:status",
    ),
    ServiceDef(
        name="plc-power",
        phase=4,
        svc_type="daemon",
        command=f"python3 {PROJECT_DIR}/services/plc-power/server.py",
        namespace="svc-plc-power",
        health_check="tcp_port",
        health_target="10.0.4.105:2404",
    ),
    ServiceDef(
        name="bms-bacnet",
        phase=4,
        svc_type="daemon",
        command=f"python3 {PROJECT_DIR}/services/rtu-sensors/server.py",
        namespace="svc-rtu-sensors",
        health_check="process",
        health_target=None,
    ),
    ServiceDef(
        name="safety-plc",
        phase=4,
        svc_type="daemon",
        command=f"python3 {PROJECT_DIR}/services/safety-sis/server.py",
        namespace="svc-safety-plc",
        health_check="tcp_port",
        health_target="10.0.5.201:102",
    ),
    ServiceDef(
        name="opcua-gateway",
        phase=4,
        svc_type="daemon",
        command=f"python3 {PROJECT_DIR}/services/opcua-gateway/server.py",
        namespace="svc-opcua",
        health_check="tcp_port",
        health_target="10.0.2.30:4840",
    ),
    # --- Phase 5: Web services ---
    ServiceDef(
        name="corp-portal",
        phase=5,
        svc_type="daemon",
        command=f"python3 {PROJECT_DIR}/services/corp-web/app/server.py",
        namespace="svc-corp-web",
        health_check="http",
        health_target="http://10.0.1.10:80/",
    ),
    ServiceDef(
        name="historian",
        phase=5,
        svc_type="daemon",
        command=f"python3 {PROJECT_DIR}/services/historian/app/server.py",
        namespace="svc-historian",
        health_check="http",
        health_target="http://10.0.2.10:8080/",
    ),
    ServiceDef(
        name="scada-hmi",
        phase=5,
        svc_type="daemon",
        command=f"python3 {PROJECT_DIR}/services/scada-hmi/app/server.py",
        namespace="svc-scada-hmi",
        health_check="tcp_port",
        health_target="10.0.3.10:8080",
    ),
    ServiceDef(
        name="safety-hmi",
        phase=5,
        svc_type="daemon",
        command=f"python3 {PROJECT_DIR}/services/safety-sis/hmi.py",
        namespace="svc-safety-hmi",
        health_check="tcp_port",
        health_target="10.0.5.202:8082",
    ),
    # --- Phase 6: SSH ---
    ServiceDef(
        name="jumphost-ssh",
        phase=6,
        svc_type="daemon",
        command=f"bash {PROJECT_DIR}/services/jumphost/run_sshd.sh",
        namespace="svc-jumphost",
        health_check="tcp_port",
        health_target="10.0.2.20:22",
    ),
    ServiceDef(
        name="ews-ssh",
        phase=6,
        svc_type="daemon",
        command=f"bash {PROJECT_DIR}/services/engineering-ws/run_sshd.sh",
        namespace="svc-eng-ws",
        health_check="tcp_port",
        health_target="10.0.3.20:22",
    ),
    # --- Phase 7: Safety bridge ---
    ServiceDef(
        name="safety-bridge",
        phase=7,
        svc_type="daemon",
        command=f"python3 {PROJECT_DIR}/services/engineering-ws/safety_bridge.py",
        namespace="svc-eng-ws",
        health_check="tcp_port",
        health_target="10.0.3.20:10102",
    ),
    # --- Phase 8: Physics engine ---
    ServiceDef(
        name="physics-engine",
        phase=8,
        svc_type="daemon",
        command=f"python3 -m physics",
        health_check="redis_key",
        health_target="physics:plant_state",
    ),
    # --- Phase 9: CTF + IDS ---
    ServiceDef(
        name="ctf-engine",
        phase=9,
        svc_type="daemon",
        command=f"python3 -m ctf",
        health_check="redis_key",
        health_target="ctf:active",
    ),
    ServiceDef(
        name="ids-engine",
        phase=9,
        svc_type="daemon",
        command=f"python3 -m services.ids-monitor",
        namespace="svc-ids",
        health_check="redis_key",
        health_target="ids:active",
    ),
    # --- Phase 10: Display ---
    ServiceDef(
        name="display-server",
        phase=2,
        svc_type="daemon",
        command=f"python3 -m display.server",
        health_check="http",
        health_target="http://127.0.0.1:5555/",
    ),
]


# ---------------------------------------------------------------------------
# Health checkers
# ---------------------------------------------------------------------------

def _check_tcp_port(target: str, timeout: float = 5.0) -> bool:
    """Check TCP connectivity to host:port."""
    try:
        host, port_s = target.rsplit(":", 1)
        port = int(port_s)
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        s.connect((host, port))
        s.close()
        return True
    except Exception:
        return False


def _check_redis_ping(target: str, timeout: float = 1.0) -> bool:
    """Ping Redis."""
    try:
        host, port_s = target.rsplit(":", 1)
        r = redis.Redis(host=host, port=int(port_s), socket_timeout=timeout)
        return r.ping()
    except Exception:
        return False


def _check_redis_key(target: str) -> bool:
    """Check if a Redis key exists."""
    try:
        r = redis.Redis(host="127.0.0.1", port=6379, decode_responses=True,
                        socket_timeout=1.0)
        return r.exists(target) > 0
    except Exception:
        return False


def _check_process(pid: Optional[int]) -> bool:
    """Check if a PID is alive."""
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _check_bridge_exists(name: str) -> bool:
    """Check if a Linux bridge exists."""
    try:
        result = subprocess.run(
            ["ip", "link", "show", name],
            capture_output=True, timeout=3,
        )
        return result.returncode == 0
    except Exception:
        return False


def _check_http(url: str, timeout: float = 5.0) -> bool:
    """HTTP GET - any 2xx/3xx/401 is healthy (401 means service is up)."""
    import urllib.request
    try:
        req = urllib.request.Request(url, method="GET")
        resp = urllib.request.urlopen(req, timeout=timeout)
        return resp.status < 500
    except urllib.error.HTTPError as e:
        # 401/403 means the service is running, just requires auth
        return e.code < 500
    except Exception:
        return False


def _check_systemd(service: str) -> bool:
    """Check systemd service is active."""
    try:
        result = subprocess.run(
            ["systemctl", "is-active", service],
            capture_output=True, text=True, timeout=5,
        )
        return result.stdout.strip() == "active"
    except Exception:
        return False


def run_health_check(svc: ServiceDef, pid: Optional[int] = None) -> bool:
    """Run the health check for a service definition with retries."""
    hc = svc.health_check
    target = svc.health_target
    if hc is None:
        return True

    def _single_check():
        if hc == "tcp_port":
            return _check_tcp_port(target)
        if hc == "redis_ping":
            return _check_redis_ping(target)
        if hc == "redis_key":
            return _check_redis_key(target)
        if hc == "process":
            return _check_process(pid)
        if hc == "bridge_exists":
            return _check_bridge_exists(target)
        if hc == "http":
            return _check_http(target)
        if hc == "systemd":
            return _check_systemd(target)
        log.warning("Unknown health check type: %s", hc)
        return False

    # Try up to 3 times with 2s delay for status checks
    for attempt in range(3):
        if _single_check():
            return True
        if attempt < 2:
            time.sleep(2)
    return False


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

class Orchestrator:
    """Top-level orchestrator for the Sysrupt OT Range."""

    def __init__(self):
        self._pids: Dict[str, int] = {}
        self._load_pids()
        self._setup_logging()

    # -- Logging ------------------------------------------------------------

    def _setup_logging(self):
        try:
            os.makedirs(LOG_DIR, exist_ok=True)
            handler = logging.FileHandler(
                os.path.join(LOG_DIR, "orchestrator.log"))
            handler.setFormatter(logging.Formatter(
                "%(asctime)s [%(levelname)s] %(message)s"
            ))
            log.addHandler(handler)
        except PermissionError:
            pass  # Non-root - skip file logging
        log.addHandler(logging.StreamHandler(sys.stdout))
        log.setLevel(logging.INFO)

    # -- PID tracking -------------------------------------------------------

    def _load_pids(self):
        try:
            if os.path.exists(PID_FILE):
                with open(PID_FILE) as f:
                    self._pids = json.load(f)
        except Exception:
            self._pids = {}

    def _save_pids(self):
        os.makedirs(PID_DIR, exist_ok=True)
        with open(PID_FILE, "w") as f:
            json.dump(self._pids, f, indent=2)

    # -- Build launch command -----------------------------------------------

    def _build_cmd(self, svc: ServiceDef) -> str:
        """Build the shell command with PYTHONPATH and optional namespace."""
        env_parts = f"PYTHONPATH={PYPATH}:{PROJECT_DIR}"
        for k, v in svc.env.items():
            env_parts += f" {k}={v}"

        if svc.namespace:
            return f"ip netns exec {svc.namespace} env {env_parts} {svc.command}"
        return f"env {env_parts} {svc.command}"

    # -- Start --------------------------------------------------------------

    def start(self):
        """Launch all services in phase order."""
        log.info("=== OT Range START ===")
        # Reset all CTF/IDS/physics/signal state for fresh start
        try:
            from orchestrator.reset import reset_scenario
            reset_scenario()
            log.info("State reset for fresh start")
        except Exception as e:
            log.warning("Reset failed: %s", e)
        os.makedirs(PID_DIR, exist_ok=True)
        os.makedirs(LOG_DIR, exist_ok=True)

        phases = sorted(set(s.phase for s in SERVICES))
        for phase in phases:
            phase_svcs = [s for s in SERVICES if s.phase == phase]
            log.info("--- Phase %d: %s ---", phase,
                     ", ".join(s.name for s in phase_svcs))

            for svc in phase_svcs:
                self._start_service(svc)

        self._save_pids()
        log.info("=== OT Range START complete")
        log.info("")
        try:
            self.r.set("orchestrator:startup:current", "complete")
            self.r.set("orchestrator:startup:phase", "done")
        except Exception:
            pass
        log.info(" ===")

    def _start_service(self, svc: ServiceDef):
        """Start a single service."""
        name = svc.name

        # Systemd services
        if svc.svc_type == "systemd":
            log.info("[%s] Ensuring systemd service is active...", name)
            subprocess.run(
                ["systemctl", "start", svc.command],
                capture_output=True, timeout=15,
            )
            # Wait for health
            if self._wait_health(svc, None, retries=5, delay=1.0):
                log.info("[%s] UP (systemd)", name)
            else:
                log.warning("[%s] health check FAILED after start", name)
            return

        # Setup scripts (run and wait)
        if svc.svc_type == "setup":
            log.info("[%s] Running setup script...", name)
            try:
                result = subprocess.run(
                    self._build_cmd(svc),
                    shell=True,
                    cwd=svc.cwd,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                if result.returncode == 0:
                    log.info("[%s] setup complete", name)
                else:
                    log.warning("[%s] setup returned %d: %s",
                                name, result.returncode, result.stderr[:200])
            except subprocess.TimeoutExpired:
                log.error("[%s] setup timed out", name)
            return

        # Daemon services - launch in background
        log.info("[%s] Starting daemon...", name)
        log_path = os.path.join(LOG_DIR, f"{name}.log")

        # If running as a different user, wrap with sudo -u
        if svc.user and svc.user != "root":
            env_str = " ".join(f"{k}={v}" for k, v in svc.env.items())
            cmd = (f"sudo -u {svc.user} env {env_str}"
                   f" PYTHONPATH={PYPATH}:{PROJECT_DIR} {svc.command}")
        else:
            cmd = self._build_cmd(svc)

        # For namespace launches, capture the real child PID
        if svc.namespace:
            bg_cmd = (
                f"ip netns exec {svc.namespace} bash -c '"
                f"PYTHONPATH={PYPATH}:{PROJECT_DIR} {svc.command} "
                f">> {log_path} 2>&1 & echo $!'"
            )
            try:
                result = subprocess.run(
                    bg_cmd, shell=True, capture_output=True, text=True,
                    cwd=svc.cwd, timeout=10,
                )
                pid_str = result.stdout.strip()
                if pid_str and pid_str.isdigit():
                    pid = int(pid_str)
                    self._pids[name] = pid
                    log.info("[%s] started in ns %s (PID %d)", name, svc.namespace, pid)
                else:
                    log.error("[%s] Failed to get PID from ns launch: %s",
                              name, result.stderr[:200])
                    return
            except Exception as exc:
                log.error("[%s] Failed to start: %s", name, exc)
                return
        else:
            log_file = open(log_path, "a")
            try:
                proc = subprocess.Popen(
                    cmd,
                    shell=True,
                    cwd=svc.cwd,
                    stdout=log_file,
                    stderr=subprocess.STDOUT,
                    preexec_fn=os.setsid,
                )
            except Exception as exc:
                log.error("[%s] Failed to start: %s", name, exc)
                log_file.close()
                return

            self._pids[name] = proc.pid
            log.info("[%s] started (PID %d)", name, proc.pid)

        pid = self._pids.get(name)
        # Wait for health check
        if self._wait_health(svc, pid, retries=10, delay=1.0):
            log.info("[%s] UP", name)
        else:
            log.warning("[%s] health check did not pass (PID %s)", name, pid)

    def _wait_health(self, svc: ServiceDef, pid: Optional[int],
                     retries: int = 5, delay: float = 1.0) -> bool:
        """Wait for a health check to pass (single-attempt per retry)."""
        if svc.health_check is None:
            return True
        hc = svc.health_check
        target = svc.health_target

        def _single():
            if hc == "tcp_port":
                return _check_tcp_port(target)
            if hc == "redis_ping":
                return _check_redis_ping(target)
            if hc == "redis_key":
                return _check_redis_key(target)
            if hc == "process":
                return _check_process(pid)
            if hc == "bridge_exists":
                return _check_bridge_exists(target)
            if hc == "http":
                return _check_http(target)
            if hc == "systemd":
                return _check_systemd(target)
            return False

        for _ in range(retries):
            if _single():
                return True
            time.sleep(delay)
        return False

    # -- Stop ---------------------------------------------------------------

    def stop(self):
        """Stop all services in reverse phase order."""
        log.info("=== OT Range STOP ===")
        self._load_pids()

        phases = sorted(set(s.phase for s in SERVICES), reverse=True)
        for phase in phases:
            phase_svcs = [s for s in SERVICES if s.phase == phase]
            for svc in reversed(phase_svcs):
                self._stop_service(svc)

        self._pids.clear()
        self._save_pids()
        log.info("=== OT Range STOP complete ===")

    def _stop_service(self, svc: ServiceDef):
        """Stop a single service."""
        name = svc.name

        if svc.svc_type == "systemd":
            log.info("[%s] Skipping systemd stop (managed externally)", name)
            return

        if svc.svc_type == "setup":
            return

        pid = self._pids.get(name)
        if pid is None:
            log.info("[%s] No PID tracked, skipping", name)
            return

        log.info("[%s] Stopping PID %d...", name, pid)
        try:
            os.killpg(os.getpgid(pid), signal.SIGTERM)
        except ProcessLookupError:
            # Try killing just the PID (namespace processes may not share pgid)
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                log.info("[%s] Already stopped", name)
                return
            except OSError:
                log.info("[%s] Cannot signal PID %d", name, pid)
                return
        except OSError:
            # Try direct kill as fallback
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                log.info("[%s] Cannot signal PID %d", name, pid)
                return

        # Wait up to 5 seconds for clean exit
        for _ in range(50):
            try:
                os.kill(pid, 0)
                time.sleep(0.1)
            except OSError:
                log.info("[%s] Stopped cleanly", name)
                return

        # Force kill
        log.warning("[%s] Sending SIGKILL to PID %d", name, pid)
        try:
            os.killpg(os.getpgid(pid), signal.SIGKILL)
        except OSError:
            try:
                os.kill(pid, signal.SIGKILL)
            except OSError:
                pass
        log.info("[%s] Killed", name)

    # -- Status -------------------------------------------------------------

    def status(self) -> Dict[str, Any]:
        """Return status of all services as a dict and print a table."""
        self._load_pids()
        results = {}
        rows = []

        for svc in SERVICES:
            pid = self._pids.get(svc.name)
            healthy = run_health_check(svc, pid)

            if svc.svc_type == "setup":
                state = "OK" if healthy else "FAIL"
            elif svc.svc_type == "systemd":
                state = "ACTIVE" if healthy else "DOWN"
            else:
                # Health check is PRIMARY - if it passes, service is UP
                if healthy:
                    state = "UP"
                else:
                    alive = _check_process(pid)
                    if alive:
                        state = "UNHEALTHY"
                    else:
                        state = "DOWN"

            results[svc.name] = {
                "phase": svc.phase,
                "type": svc.svc_type,
                "pid": pid,
                "state": state,
                "healthy": healthy,
            }
            pid_str = str(pid) if pid else "-"
            rows.append((svc.phase, svc.name, svc.svc_type, pid_str, state))

        # Print formatted table
        header = f"{'PH':>2}  {'SERVICE':<22} {'TYPE':<8} {'PID':>7}  {'STATE':<10}"
        print()
        print("=" * len(header))
        print("  SYSRUPT OT RANGE STATUS")
        print("=" * len(header))
        print(header)
        print("-" * len(header))
        for ph, name, stype, pid_s, state in rows:
            marker = "+" if state in ("UP", "OK", "ACTIVE") else "-"
            print(f"{ph:>2}  {name:<22} {stype:<8} {pid_s:>7}  [{marker}] {state}")
        print("=" * len(header))
        print()

        return results

    # -- Reset --------------------------------------------------------------

    def reset(self):
        """Full reset: stop all services, clear all state, restart everything fresh."""
        log.info("=== FULL RESET ===")
        
        # Step 1: Stop ALL services (reverse order)
        self.stop()
        time.sleep(2)
        
        # Step 2: Kill any orphan python3 processes (except orchestrator itself)
        import subprocess
        my_pid = os.getpid()
        # Explicitly kill CTF engine processes to prevent duplicate instances
        subprocess.run("pkill -9 -f 'python3 -m ctf'", shell=True, capture_output=True)
        subprocess.run("pkill -9 -f 'python3 -m services.ids-monitor'", shell=True, capture_output=True)
        time.sleep(0.5)
        result = subprocess.run("pgrep -a python3", shell=True, capture_output=True, text=True)
        for line in result.stdout.strip().split("\n"):
            if not line.strip():
                continue
            pid = int(line.split()[0])
            if pid != my_pid and "orchestrator" not in line:
                try:
                    os.kill(pid, 9)
                except ProcessLookupError:
                    pass
        time.sleep(1)
        
        # Step 3: Flush ALL application state from Redis (keep system keys)
        try:
            r = redis.Redis(host="127.0.0.1", port=6379, decode_responses=True)
            r.flushdb()
            log.info("Redis flushed")
        except Exception as e:
            log.warning("Redis flush failed: %s", e)
        
        # Step 4: Start everything fresh
        self.start()
        
        log.info("=== FULL RESET COMPLETE ===")
        print("Full reset complete - ready for new player")


    # -- Health -------------------------------------------------------------

    def health(self) -> Dict[str, bool]:
        """Run all health checks and return results."""
        self._load_pids()
        results = {}
        for svc in SERVICES:
            pid = self._pids.get(svc.name)
            results[svc.name] = run_health_check(svc, pid)
        return results
