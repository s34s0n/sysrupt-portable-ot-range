"""Event bus - Redis pub/sub channels and key constants."""

import json
import logging
import threading
from typing import Any, Callable, Dict

import redis

log = logging.getLogger("event_bus")

# ---------------------------------------------------------------------------
# Well-known pub/sub channels
# ---------------------------------------------------------------------------

class EventChannels:
    """All pub/sub channel names used across the OT Range."""

    # Physics engine
    PHYSICS_STATE = "physics:state"
    PHYSICS_PLC_INTAKE = "physics:plc:intake:inputs"
    PHYSICS_PLC_CHEMICAL = "physics:plc:chemical:inputs"
    PHYSICS_PLC_FILTRATION = "physics:plc:filtration:inputs"
    PHYSICS_PLC_DISTRIBUTION = "physics:plc:distribution:inputs"
    PHYSICS_PLC_POWER = "physics:plc:power:inputs"
    PHYSICS_SIS_INPUTS = "physics:sis:inputs"
    PHYSICS_BMS_SENSORS = "physics:bms:sensors:inputs"

    # CTF
    CTF_FLAG_CAPTURED = "ctf:flag_captured"

    # IDS
    IDS_ALERT = "ids:alert"

    # Safety
    SAFETY_TRIP = "safety:trip"

    # Display
    DISPLAY_UPDATE = "display:update"

    # Hardware
    HARDWARE_EVENT = "hardware:event"

    # Service lifecycle
    SERVICE_STATE = "service:state"

    # Network
    NETWORK_EVENT = "network:event"


# ---------------------------------------------------------------------------
# Well-known Redis keys
# ---------------------------------------------------------------------------

class RedisKeys:
    """All Redis keys used across the OT Range."""

    # Physics
    PHYSICS_PLANT_STATE = "physics:plant_state"
    PHYSICS_VICTORY = "physics:victory"

    # CTF
    CTF_ACTIVE = "ctf:active"
    CTF_SCORE = "ctf:score"
    CTF_FLAGS_CAPTURED = "ctf:flags_captured"
    CTF_START_TIME = "ctf:start_time"
    CTF_LAST_FLAG_TIME = "ctf:last_flag_time"
    CTF_TOTAL_CHALLENGES = "ctf:total_challenges"
    CTF_TOTAL_POINTS = "ctf:total_points"
    CTF_HINT_STATE = "ctf:hint_state"

    # IDS
    IDS_ACTIVE = "ids:active"
    IDS_ALERT_COUNT = "ids:alert_count"
    IDS_THREAT_LEVEL = "ids:threat_level"
    IDS_ALERTS = "ids:alerts"
    IDS_LATEST_ALERT = "ids:latest_alert"

    # Hardware
    HW_STATUS = "hw:status"

    # Service / login tracking
    CORP_ADMIN_LOGIN = "corp:admin_login"
    SCADA_HMI_LOGIN = "scada:hmi_login"


EVENT_CHANNELS = EventChannels


# ---------------------------------------------------------------------------
# EventBus implementation
# ---------------------------------------------------------------------------

class EventBus:
    """Publish/subscribe event bus backed by Redis pub/sub."""

    def __init__(self, host: str = "127.0.0.1", port: int = 6379, db: int = 0):
        self.host = host
        self.port = port
        self.db = db
        self._redis = redis.Redis(host=host, port=port, db=db,
                                  decode_responses=True, socket_timeout=3.0)
        self._pubsub = None
        self._thread = None

    def publish(self, channel: str, data: Dict[str, Any]) -> int:
        """Publish JSON-serialised data to a channel."""
        payload = json.dumps(data)
        return self._redis.publish(channel, payload)

    def subscribe(self, channel: str, callback: Callable[[Dict[str, Any]], None]):
        """Subscribe to a channel - callback receives parsed JSON dicts.

        Runs the listener in a daemon thread.
        """
        if self._pubsub is None:
            self._pubsub = self._redis.pubsub(ignore_subscribe_messages=True)

        def _handler(message):
            try:
                data = json.loads(message["data"])
                callback(data)
            except Exception as exc:
                log.warning("EventBus handler error on %s: %s", channel, exc)

        self._pubsub.subscribe(**{channel: _handler})

        if self._thread is None or not self._thread.is_alive():
            self._thread = self._pubsub.run_in_thread(sleep_time=0.1,
                                                       daemon=True)

    def close(self):
        """Clean up."""
        if self._thread is not None:
            self._thread.stop()
            self._thread = None
        if self._pubsub is not None:
            self._pubsub.close()
            self._pubsub = None
