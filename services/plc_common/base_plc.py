"""
Base PLC class for the Sysrupt OT Range.

Provides a Modbus TCP server (pymodbus 3.x async), a deterministic scan
cycle loop, Redis state publishing, Modbus write event logging, and
physics-engine input injection via Redis pub/sub.

Subclasses define register layout and override ``scan_cycle()`` to
implement their ladder logic in Python.
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from datetime import datetime, timezone
from typing import List, Optional

import redis
from pymodbus.datastore import (
    ModbusDeviceContext,
    ModbusSequentialDataBlock,
    ModbusServerContext,
)
from pymodbus.server import StartAsyncTcpServer

log = logging.getLogger(__name__)


class LoggingDataBlock(ModbusSequentialDataBlock):
    """ModbusSequentialDataBlock that publishes every write to Redis."""

    def __init__(self, address, values, plc_ref, block_name):
        super().__init__(address, values)
        self._plc_ref = plc_ref
        self._block_name = block_name  # "holding" | "coils" | "input" | "discrete"

    def setValues(self, address, values):  # noqa: N802 - pymodbus API
        super().setValues(address, values)
        try:
            plc = self._plc_ref()
            if plc is not None and plc._initialised:
                # Subtract the leading padding slot for the public address.
                plc.log_modbus_write(
                    self._block_name, max(address - 1, 0), values
                )
        except Exception as exc:  # pragma: no cover
            log.debug("setValues hook failed: %s", exc)


class BasePLC:
    """Base class for all Sysrupt PLCs."""

    PLC_NAME: str = "Base PLC"
    PLC_ID: str = "base"
    BIND_IP: str = "0.0.0.0"
    BIND_PORT: int = 502
    SCAN_PERIOD_S: float = 0.05  # 50 ms / 20 Hz
    PUBLISH_EVERY_N_SCANS: int = 10  # 500 ms by default
    ST_FILE_PATH: Optional[str] = None

    INITIAL_HOLDING: List[int] = []
    INITIAL_INPUT: List[int] = []
    INITIAL_COILS: List[bool] = []
    INITIAL_DISCRETE: List[bool] = []

    REDIS_HOST = "127.0.0.1"
    REDIS_PORT = 6379

    def __init__(self):
        import weakref

        self._initialised = False
        self._self_ref = weakref.ref(self)

        # Data blocks.  pymodbus 3.12 no longer supports ``zero_mode`` so
        # Modbus address N maps to values[N+1] internally. We pad every
        # block with one leading zero and size it generously so address 0
        # is the first user register. The :py:meth:`get_*`/:py:meth:`set_*`
        # helpers below also compensate by using ``addr + 1``.
        pad = [0]
        self._hr_len = max(len(self.INITIAL_HOLDING), 1)
        self._ir_len = max(len(self.INITIAL_INPUT), 1)
        self._co_len = max(len(self.INITIAL_COILS), 1)
        self._di_len = max(len(self.INITIAL_DISCRETE), 1)
        hr_init = pad + list(self.INITIAL_HOLDING or [0])
        ir_init = pad + list(self.INITIAL_INPUT or [0])
        co_init = pad + [1 if v else 0 for v in (self.INITIAL_COILS or [False])]
        di_init = pad + [1 if v else 0 for v in (self.INITIAL_DISCRETE or [False])]

        self._hr_block = LoggingDataBlock(
            0, hr_init, self._self_ref, "holding"
        )
        self._ir_block = LoggingDataBlock(
            0, ir_init, self._self_ref, "input"
        )
        self._co_block = LoggingDataBlock(
            0, co_init, self._self_ref, "coils"
        )
        self._di_block = LoggingDataBlock(
            0, di_init, self._self_ref, "discrete"
        )

        device_ctx = ModbusDeviceContext(
            hr=self._hr_block,
            ir=self._ir_block,
            co=self._co_block,
            di=self._di_block,
        )
        self._context = ModbusServerContext(devices=device_ctx, single=True)

        self.scan_count = 0
        self.scan_time_ms = 0.0
        self.status = "stopped"
        self._scan_paused = False
        self._stop_event = threading.Event()
        self._scan_thread: Optional[threading.Thread] = None
        self._server_thread: Optional[threading.Thread] = None
        self._sub_thread: Optional[threading.Thread] = None
        self._server_loop: Optional[asyncio.AbstractEventLoop] = None
        self._server_task = None
        self._alt_timer = 0

        # Redis (dynamic host detection across network namespaces)
        self._redis = None
        host = self._get_redis_host()
        if host is None:
            log.warning("[%s] Redis unavailable on any candidate host - degraded mode", self.PLC_ID)
        else:
            try:
                self._redis = redis.Redis(
                    host=host, port=self.REDIS_PORT, decode_responses=True
                )
                self._redis.ping()
                self.REDIS_HOST = host
            except Exception as exc:
                log.warning("[%s] Redis unavailable at %s: %s", self.PLC_ID, host, exc)
                self._redis = None

        self._initialised = True

    def _get_redis_host(self):
        """Determine the correct Redis host for the current network context.

        Namespaced services cannot reach 127.0.0.1 on the host, so we try
        the bridge gateway addresses. First responsive one wins.
        """
        candidates = [
            self.REDIS_HOST,
            "10.0.4.1",
            "10.0.5.1",
            "10.0.3.1",
            "10.0.2.1",
            "10.0.1.1",
        ]
        for host in candidates:
            try:
                r = redis.Redis(
                    host=host,
                    port=self.REDIS_PORT,
                    socket_timeout=1,
                    socket_connect_timeout=1,
                )
                r.ping()
                return host
            except Exception:
                continue
        return None

    # ------------------------------------------------------------------ #
    # lifecycle
    # ------------------------------------------------------------------ #
    def start(self):
        """Start modbus server, scan thread, and redis subscriber."""
        self._stop_event.clear()
        self.status = "running"

        self._server_thread = threading.Thread(
            target=self._run_server, name=f"{self.PLC_ID}-modbus", daemon=True
        )
        self._server_thread.start()

        self._scan_thread = threading.Thread(
            target=self._scan_loop, name=f"{self.PLC_ID}-scan", daemon=True
        )
        self._scan_thread.start()

        self._sub_thread = threading.Thread(
            target=self._subscribe_physics, name=f"{self.PLC_ID}-sub", daemon=True
        )
        self._sub_thread.start()

        # Give the server a moment to bind.
        time.sleep(0.3)
        log.info(
            "[%s] Started on %s:%d", self.PLC_ID, self.BIND_IP, self.BIND_PORT
        )

    def stop(self):
        self.status = "stopped"
        self._stop_event.set()
        # Stop async server
        if self._server_loop is not None:
            try:
                self._server_loop.call_soon_threadsafe(self._server_loop.stop)
            except Exception:  # pragma: no cover
                pass
        if self._scan_thread is not None:
            self._scan_thread.join(timeout=2.0)
        if self._redis is not None:
            try:
                self._redis.set(f"plc:{self.PLC_ID}:status", "stopped")
            except Exception:
                pass

    # ------------------------------------------------------------------ #
    # async modbus server
    # ------------------------------------------------------------------ #
    def _run_server(self):
        loop = asyncio.new_event_loop()
        self._server_loop = loop
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(
                StartAsyncTcpServer(
                    context=self._context,
                    address=(self.BIND_IP, self.BIND_PORT),
                )
            )
        except Exception as exc:
            log.error("[%s] Modbus server stopped: %s", self.PLC_ID, exc)
        finally:
            try:
                loop.close()
            except Exception:
                pass

    # ------------------------------------------------------------------ #
    # scan loop
    # ------------------------------------------------------------------ #
    def _scan_loop(self):
        while not self._stop_event.is_set():
            t0 = time.monotonic()
            if not self._scan_paused:
                try:
                    self.scan_cycle()
                except Exception as exc:
                    log.exception("[%s] scan_cycle error: %s", self.PLC_ID, exc)
                self.scan_count += 1
                self.scan_time_ms = (time.monotonic() - t0) * 1000.0
                if self.scan_count % self.PUBLISH_EVERY_N_SCANS == 0:
                    try:
                        self.publish_state()
                    except Exception as exc:
                        log.debug("publish_state failed: %s", exc)
            remaining = self.SCAN_PERIOD_S - (time.monotonic() - t0)
            if remaining > 0:
                time.sleep(remaining)

    def scan_pause(self):
        self._scan_paused = True

    def scan_resume(self):
        self._scan_paused = False

    def scan_cycle(self):
        """Override in subclass."""
        raise NotImplementedError

    # ------------------------------------------------------------------ #
    # redis state
    # ------------------------------------------------------------------ #
    def _snapshot(self):
        # Skip the first padding slot (see __init__).
        hr = list(self._hr_block.values[1 : 1 + self._hr_len])
        ir = list(self._ir_block.values[1 : 1 + self._ir_len])
        co = [bool(v) for v in self._co_block.values[1 : 1 + self._co_len]]
        di = [bool(v) for v in self._di_block.values[1 : 1 + self._di_len]]
        return hr, ir, co, di

    def publish_state(self):
        if self._redis is None:
            return
        hr, ir, co, di = self._snapshot()
        pid = self.PLC_ID
        pipe = self._redis.pipeline()
        pipe.set(f"plc:{pid}:status", self.status)
        pipe.set(f"plc:{pid}:holding", json.dumps(hr))
        pipe.set(f"plc:{pid}:inputs", json.dumps(ir))
        pipe.set(f"plc:{pid}:coils", json.dumps(co))
        pipe.set(f"plc:{pid}:discrete", json.dumps(di))
        pipe.set(f"plc:{pid}:scan_count", self.scan_count)
        pipe.set(f"plc:{pid}:scan_time_ms", f"{self.scan_time_ms:.3f}")
        full = {
            "plc_id": pid,
            "plc_name": self.PLC_NAME,
            "status": self.status,
            "scan_count": self.scan_count,
            "scan_time_ms": round(self.scan_time_ms, 3),
            "holding": hr,
            "inputs": ir,
            "coils": co,
            "discrete": di,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        pipe.set(f"plc:{pid}:full_state", json.dumps(full))
        pipe.execute()

    def log_modbus_write(self, block_name, address, values, source_ip="unknown"):
        if self._redis is None:
            return
        fc_map = {"holding": 6, "coils": 5, "input": 4, "discrete": 2}
        event = {
            "plc_id": self.PLC_ID,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source_ip": source_ip,
            "function_code": fc_map.get(block_name, 0),
            "register_type": block_name,
            "address": address,
            "values": list(values) if hasattr(values, "__iter__") else [values],
            "description": f"{block_name} write @{address}",
        }
        try:
            self._redis.publish("modbus.write", json.dumps(event))
            self._redis.lpush(
                f"plc:{self.PLC_ID}:write_log", json.dumps(event)
            )
            self._redis.ltrim(f"plc:{self.PLC_ID}:write_log", 0, 999)
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    # physics subscription
    # ------------------------------------------------------------------ #
    def _subscribe_physics(self):
        if self._redis is None:
            return
        try:
            pubsub = self._redis.pubsub()
            pubsub.subscribe(f"physics:plc:{self.PLC_ID}:inputs")
        except Exception as exc:
            log.debug("physics subscribe failed: %s", exc)
            return
        while not self._stop_event.is_set():
            try:
                msg = pubsub.get_message(timeout=0.5, ignore_subscribe_messages=True)
            except Exception:
                msg = None
            if msg and msg.get("type") == "message":
                try:
                    data = json.loads(msg["data"])
                    self.update_inputs_from_physics(data)
                except Exception as exc:
                    log.debug("bad physics msg: %s", exc)

    def update_inputs_from_physics(self, data):
        """data: dict of {register_index: value} for input registers."""
        for k, v in data.items():
            try:
                self.set_input(int(k), int(v))
            except Exception:
                continue

    # ------------------------------------------------------------------ #
    # register helpers
    # ------------------------------------------------------------------ #
    # All helpers use ``addr + 1`` because of the leading padding slot.
    def get_holding(self, addr):
        return self._hr_block.values[addr + 1]

    def set_holding(self, addr, value):
        self._hr_block.values[addr + 1] = int(value) & 0xFFFF

    def get_input(self, addr):
        return self._ir_block.values[addr + 1]

    def set_input(self, addr, value):
        if addr + 1 >= len(self._ir_block.values):
            return
        self._ir_block.values[addr + 1] = int(value) & 0xFFFF

    def get_coil(self, addr):
        return bool(self._co_block.values[addr + 1])

    def set_coil(self, addr, value):
        self._co_block.values[addr + 1] = 1 if value else 0

    def get_discrete(self, addr):
        return bool(self._di_block.values[addr + 1])

    def set_discrete(self, addr, value):
        self._di_block.values[addr + 1] = 1 if value else 0
