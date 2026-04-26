"""PLC-4 Distribution - EtherNet/IP (CIP) server.

Uses cpppo's built-in EtherNet/IP server as a subprocess with a set of
predefined tags that a standard master (e.g. Studio 5000 Emulate, pylogix,
or cpppo's own client) can read and write. A supervisor loop keeps the
subprocess alive, updates tag values periodically via cpppo's client API
to simulate physics, and publishes state to Redis.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import random
import signal
import socket
import subprocess
import sys
import threading
import time

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import redis  # noqa: E402

log = logging.getLogger("plc-distribution")


# Tag layout is exposed to CIP as a set of atomic arrays.
TAGS = [
    ("OUTLET_PRESSURE", "INT", 10),
    ("BOOSTER_FLOW", "INT", 10),
    ("RESERVOIR_LEVEL", "INT", 10),
    ("DIST_TEMP", "INT", 10),
    ("SYSTEM_STATUS", "INT", 10),
    ("OUTLET_VALVE_CMD", "INT", 10),
    ("BOOSTER_PUMP_SPEED", "INT", 10),
    ("PRESSURE_SP", "INT", 10),
    ("MODE_SELECT", "INT", 10),
    ("ALARM_ENABLE", "INT", 10),
    ("ALARM_THRESHOLD", "INT", 10),
]


class DistributionENIP:
    PLC_NAME = "PLC-4 Distribution EtherNet/IP Server"
    PLC_ID = "distribution"

    def __init__(self, bind_ip: str = "0.0.0.0", bind_port: int = 44818):
        self.bind_ip = bind_ip
        self.bind_port = bind_port

        # Local simulated state (mirrors subprocess tags).
        self.state = {
            "OUTLET_PRESSURE": [420, 418, 422, 419, 421, 0, 0, 0, 0, 0],
            "BOOSTER_FLOW": [850, 860, 845, 855, 850, 0, 0, 0, 0, 0],
            "RESERVOIR_LEVEL": [7500, 7480, 7510, 7495, 7502, 0, 0, 0, 0, 0],
            "DIST_TEMP": [185, 187, 184, 186, 185, 0, 0, 0, 0, 0],
            "SYSTEM_STATUS": [1, 0, 0, 0, 0, 0, 0, 0, 0, 0],
            "OUTLET_VALVE_CMD": [75, 0, 0, 0, 0, 0, 0, 0, 0, 0],
            "BOOSTER_PUMP_SPEED": [62, 0, 0, 0, 0, 0, 0, 0, 0, 0],
            "PRESSURE_SP": [420, 0, 0, 0, 0, 0, 0, 0, 0, 0],
            "MODE_SELECT": [1, 0, 0, 0, 0, 0, 0, 0, 0, 0],
            "ALARM_ENABLE": [1, 0, 0, 0, 0, 0, 0, 0, 0, 0],
            "ALARM_THRESHOLD": [800, 0, 0, 0, 0, 0, 0, 0, 0, 0],
        }
        self._ch6_solved = False

        self._proc: subprocess.Popen | None = None
        self._running = False
        self._redis = None
        self._connect_redis()

    def _connect_redis(self):
        for host in ["127.0.0.1", "10.0.4.1", "10.0.5.1", "10.0.3.1", "10.0.2.1", "10.0.1.1"]:
            try:
                r = redis.Redis(
                    host=host,
                    port=6379,
                    socket_timeout=1,
                    socket_connect_timeout=1,
                    decode_responses=True,
                )
                r.ping()
                self._redis = r
                log.info("redis connected at %s", host)
                return
            except Exception:
                continue
        log.warning("redis unavailable - degraded mode")

    def _publish_state(self):
        if not self._redis:
            return
        state = {
            "plc_id": self.PLC_ID,
            "status": "running" if self._proc and self._proc.poll() is None else "stopped",
            "protocol": "ethernet-ip",
            "port": self.bind_port,
            "tags": self.state,
            "ts": time.time(),
        }
        try:
            pipe = self._redis.pipeline()
            pipe.set(f"plc:{self.PLC_ID}:status", state["status"])
            pipe.set(f"plc:{self.PLC_ID}:tags", json.dumps(self.state))
            pipe.set(f"plc:{self.PLC_ID}:full_state", json.dumps(state))
            pipe.execute()
        except Exception as exc:
            log.debug("redis publish failed: %s", exc)

    def _spawn_cpppo(self):
        """Spawn cpppo's enip server as a subprocess."""
        tag_args = [f"{name}={typ}[{size}]" for name, typ, size in TAGS]
        cmd = [
            sys.executable,
            "-u",
            "-m",
            "cpppo.server.enip",
            "--address",
            f"{self.bind_ip}:{self.bind_port}",
        ] + tag_args
        log.info("spawning cpppo: %s", " ".join(cmd))
        env = os.environ.copy()
        env.setdefault("PYTHONUNBUFFERED", "1")
        self._proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            env=env,
            text=True,
        )
        threading.Thread(target=self._drain_stdout, daemon=True).start()
        threading.Thread(target=self._monitor_connections, daemon=True).start()


    def _monitor_connections(self):
        """Detect EtherNet/IP client connections from external IPs only.

        Health checks come from the gateway (10.0.4.1) or localhost -- those
        are filtered out.  Only connections from process-zone IPs (EWS
        10.0.4.20, SCADA 10.0.3.x, etc.) count as student interactions.
        """
        import subprocess
        # Wait long enough for health checks to finish after a reset
        time.sleep(60)
        published = False

        # IPs that are NOT student traffic (gateway, localhost)
        IGNORED_IPS = {"0A000401", "7F000001"}  # 10.0.4.1, 127.0.0.1 in hex

        def _get_external_conns():
            """Return set of remote-address hex strings on port AF12 from external IPs."""
            try:
                result = subprocess.run(
                    ["cat", "/proc/net/tcp"],
                    capture_output=True, text=True, timeout=2
                )
                conns = set()
                for line in result.stdout.strip().split("\n")[1:]:
                    parts = line.split()
                    if len(parts) < 4:
                        continue
                    local = parts[1]
                    remote = parts[2]
                    # local_port is after the colon in local address
                    if local.split(":")[1].upper() == "AF12":
                        remote_ip = remote.split(":")[0].upper()
                        if remote_ip not in IGNORED_IPS:
                            conns.add(remote)
                return conns
            except Exception:
                return set()

        baseline = _get_external_conns()

        while not published:
            current = _get_external_conns()
            new_conns = current - baseline
            if new_conns:
                if self._redis:
                    self._redis.publish("ot.protocol.write", json.dumps({
                        "plc_id": self.PLC_ID,
                        "protocol": "enip",
                        "operation": "get_attribute",
                        "class_id": 100,
                        "ts": time.time(),
                    }))
                    log.info("CTF: EtherNet/IP client interaction detected (external)")
                    published = True
                baseline = current
            time.sleep(0.5)

    def _drain_stdout(self):
        if not self._proc or not self._proc.stdout:
            return
        for line in self._proc.stdout:
            stripped = line.rstrip()
            log.debug("cpppo: %s", stripped)
            # CTF: detect CIP writes and publish ot.protocol.write
            if any(kw in stripped for kw in ["Set Attribute", "Get Attribute", "read", "write", "Read"]):
                try:
                    if self._redis:
                        self._redis.publish("ot.protocol.write", json.dumps({
                            "plc_id": self.PLC_ID,
                            "protocol": "enip",
                            "operation": "get_attribute" if "Get" in stripped or "read" in stripped.lower() or "Read" in stripped else "set_attribute",
                            "class_id": 100,
                            "raw": stripped,
                            "ts": time.time(),
                        }))
                except Exception:
                    pass

    def _wait_for_port(self, timeout: float = 8.0) -> bool:
        """Poll until the cpppo subprocess is actually listening on the port."""
        test_ip = "127.0.0.1" if self.bind_ip in ("0.0.0.0", "") else self.bind_ip
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self._proc and self._proc.poll() is not None:
                log.error("cpppo exited early with rc=%s", self._proc.returncode)
                return False
            try:
                s = socket.create_connection((test_ip, self.bind_port), timeout=0.5)
                s.close()
                return True
            except OSError:
                time.sleep(0.2)
        return False

    def _read_tag_from_cpppo(self, tag):
        """Read current tag value from the cpppo subprocess."""
        try:
            result = subprocess.run(
                [sys.executable, "-m", "cpppo.server.enip.client",
                 "--print",
                 "--address", "0.0.0.0:%d" % self.bind_port,
                 "%s" % tag],
                capture_output=True, text=True, timeout=3,
            )
            # Parse output like: "ALARM_ENABLE              == [1]: 'OK'"
            for line in result.stdout.strip().split("\n"):
                if "==" in line and "[" in line:
                    val_part = line.split("==")[1].strip()
                    # Extract value from "[1]: 'OK'"
                    val_str = val_part.split("]")[0].strip(" [")
                    return int(val_str)
        except Exception:
            pass
        return None

    def _reset_tags(self):
        """Reset all tags to safe defaults after alarm trigger."""
        try:
            writes = [
                "BOOSTER_PUMP_SPEED[0]=62",
                "MODE_SELECT[0]=1",
                "ALARM_ENABLE[0]=1",
                "PRESSURE_SP[0]=420",
            ]
            subprocess.run(
                [sys.executable, "-m", "cpppo.server.enip.client",
                 "--address", "0.0.0.0:%d" % self.bind_port] + writes,
                capture_output=True, text=True, timeout=3,
            )
            # Reset local state
            self.state["OUTLET_PRESSURE"][0] = 420
            self.state["BOOSTER_PUMP_SPEED"][0] = 62
            self.state["MODE_SELECT"][0] = 1
            self.state["ALARM_ENABLE"][0] = 1
            self.state["PRESSURE_SP"][0] = 420
            log.info("CH-06: Tags reset to defaults after alarm trigger")
        except Exception:
            pass

    def _physics_loop(self):
        """Simulate pressure based on pump speed and mode, detect overpressure."""
        while self._running:
            try:
                # Detect orchestrator reset: if ctf:score goes to 0, clear solved flag
                if self._ch6_solved and self._redis:
                    try:
                        score = self._redis.get("ctf:score")
                        if score == "0":
                            self._ch6_solved = False
                            self._reset_tags()
                            log.info("CH-06: Reset detected, cleared solved state")
                    except Exception:
                        pass

                # Read current tag values written by students
                for tag in ["BOOSTER_PUMP_SPEED", "MODE_SELECT", "ALARM_ENABLE",
                            "ALARM_THRESHOLD", "PRESSURE_SP"]:
                    val = self._read_tag_from_cpppo(tag)
                    if val is not None:
                        self.state[tag][0] = val

                mode = self.state["MODE_SELECT"][0]
                pump_speed = self.state["BOOSTER_PUMP_SPEED"][0]
                alarm_en = self.state["ALARM_ENABLE"][0]
                alarm_thresh = self.state["ALARM_THRESHOLD"][0]
                if alarm_thresh == 0:
                    alarm_thresh = 800

                # Simulate pressure based on pump speed
                if mode == 0:  # Manual mode - pressure follows pump speed
                    target = int(pump_speed * 12)  # speed 100 -> pressure ~1200
                    current = self.state["OUTLET_PRESSURE"][0]
                    # Ramp toward target - visible in ~20 seconds
                    diff = target - current
                    step = max(10, abs(diff) // 5)
                    if current < target:
                        current = min(current + step + random.randint(0, 10), target)
                    elif current > target:
                        current = max(current - step - random.randint(0, 10), target)
                    self.state["OUTLET_PRESSURE"][0] = current
                else:
                    # Auto mode - drift around setpoint
                    sp = self.state["PRESSURE_SP"][0]
                    for i in range(5):
                        self.state["OUTLET_PRESSURE"][i] = max(
                            300, min(600, sp + random.randint(-3, 3))
                        )

                # Drift other values normally
                for i in range(5):
                    self.state["BOOSTER_FLOW"][i] = max(
                        0, min(1500, self.state["BOOSTER_FLOW"][i] + random.randint(-5, 5))
                    )
                    self.state["RESERVOIR_LEVEL"][i] = max(
                        0, min(10000, self.state["RESERVOIR_LEVEL"][i] + random.randint(-10, 10))
                    )
                    self.state["DIST_TEMP"][i] = max(
                        0, min(400, self.state["DIST_TEMP"][i] + random.randint(-1, 1))
                    )

                pressure = self.state["OUTLET_PRESSURE"][0]

                # Overpressure detection
                if pressure > alarm_thresh:
                    if alarm_en == 1:
                        # Alarm fires! Reset challenge.
                        log.info("CH-06: ALARM TRIGGERED! Pressure %d > %d. Resetting.",
                                 pressure, alarm_thresh)
                        if self._redis:
                            self._redis.publish("ot.protocol.write", json.dumps({
                                "plc_id": self.PLC_ID,
                                "protocol": "enip",
                                "event": "alarm_triggered",
                                "pressure": pressure,
                                "threshold": alarm_thresh,
                                "ts": time.time(),
                            }))
                        self._reset_tags()
                    elif not self._ch6_solved:
                        # Alarm disabled + overpressure = CHALLENGE SOLVED!
                        log.info("CH-06: SOLVED! Pressure %d > %d with alarm disabled!",
                                 pressure, alarm_thresh)
                        self._ch6_solved = True
                        self._ch6_solve_time = time.time()
                        if self._redis:
                            self._redis.publish("ot.protocol.write", json.dumps({
                                "plc_id": self.PLC_ID,
                                "protocol": "enip",
                                "event": "silent_overpressure",
                                "pressure": pressure,
                                "threshold": alarm_thresh,
                                "ts": time.time(),
                            }))

                # Reset tags 10 seconds after solve (non-blocking)
                if self._ch6_solved and hasattr(self, '_ch6_solve_time'):
                    if time.time() - self._ch6_solve_time > 10:
                        self._reset_tags()
                        del self._ch6_solve_time
                        log.info("CH-06: Tags reset after solve")

                self._publish_state()
            except Exception as exc:
                log.debug("physics tick error: %s", exc)
            time.sleep(2.0)

    def start(self):
        self._running = True
        self._spawn_cpppo()
        if not self._wait_for_port():
            log.error("cpppo failed to bind to %s:%d", self.bind_ip, self.bind_port)
            self._running = False
            if self._proc:
                self._proc.terminate()
            return False
        log.info("cpppo EtherNet/IP server listening on %s:%d", self.bind_ip, self.bind_port)
        print(
            f"[PLC-4] EtherNet/IP server listening on {self.bind_ip}:{self.bind_port}",
            flush=True,
        )
        # Write initial values to cpppo tags
        try:
            init_writes = [
                "OUTLET_PRESSURE[0]=420",
                "BOOSTER_PUMP_SPEED[0]=62",
                "MODE_SELECT[0]=1",
                "ALARM_ENABLE[0]=1",
                "ALARM_THRESHOLD[0]=800",
                "PRESSURE_SP[0]=420",
            ]
            subprocess.run(
                [sys.executable, "-m", "cpppo.server.enip.client",
                 "--address", "0.0.0.0:%d" % self.bind_port] + init_writes,
                capture_output=True, text=True, timeout=5,
            )
            log.info("Initial tag values written to cpppo")
        except Exception:
            pass
        self._publish_state()
        t = threading.Thread(target=self._physics_loop, daemon=True)
        t.start()
        return True

    def stop(self):
        self._running = False
        if self._proc and self._proc.poll() is None:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=3)
            except Exception:
                try:
                    self._proc.kill()
                except Exception:
                    pass

    def wait(self):
        try:
            while self._running and self._proc and self._proc.poll() is None:
                time.sleep(0.5)
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()


def main():
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    )
    parser = argparse.ArgumentParser()
    parser.add_argument("--bind", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=44818)
    args = parser.parse_args()

    plc = DistributionENIP(bind_ip=args.bind, bind_port=args.port)

    def _handle_sig(signum, frame):
        plc.stop()

    signal.signal(signal.SIGINT, _handle_sig)
    signal.signal(signal.SIGTERM, _handle_sig)

    if not plc.start():
        sys.exit(1)
    plc.wait()


if __name__ == "__main__":
    main()
