"""Redis publisher for hardware state and events."""
from __future__ import annotations

import json
import logging
from typing import Callable

import redis

log = logging.getLogger(__name__)


class HardwareRedisPublisher:
    """Publishes hardware state and events to Redis."""

    def __init__(self, redis_config: dict):
        self.host = redis_config.get("host", "127.0.0.1")
        self.port = int(redis_config.get("port", 6379))
        self.db = int(redis_config.get("db", 0))
        self.prefix = redis_config.get("prefix", "hw:")
        self.publish_channel = redis_config.get("publish_channel", "hardware.state")
        self.client = redis.Redis(
            host=self.host, port=self.port, db=self.db, decode_responses=True
        )
        self._pubsub_threads: list = []

    def publish_state(self, state: dict) -> None:
        try:
            pipe = self.client.pipeline()
            pipe.set(f"{self.prefix}mode", str(state.get("mode", "")))
            for sid, value in state.get("temperatures", {}).items():
                pipe.set(f"{self.prefix}temp:{sid}", str(value))
            for rid, rstate in state.get("relays", {}).items():
                pipe.set(f"{self.prefix}relay:{rid}", "1" if rstate else "0")
            for lid, lstate in state.get("leds", {}).items():
                pipe.set(f"{self.prefix}led:{lid}", str(lstate))
            pipe.set(f"{self.prefix}uptime", str(state.get("uptime_seconds", 0)))
            pipe.set(f"{self.prefix}full_state", json.dumps(state))
            pipe.execute()
            self.client.publish(self.publish_channel, json.dumps(state))
        except redis.RedisError as e:
            log.error("Redis publish_state failed: %s", e)

    def publish_event(self, channel: str, event: dict) -> None:
        try:
            self.client.publish(channel, json.dumps(event))
        except redis.RedisError as e:
            log.error("Redis publish_event failed: %s", e)

    def get_state(self) -> dict:
        try:
            raw = self.client.get(f"{self.prefix}full_state")
            if not raw:
                return {}
            return json.loads(raw)
        except (redis.RedisError, json.JSONDecodeError) as e:
            log.error("Redis get_state failed: %s", e)
            return {}

    def subscribe(self, channel: str, callback: Callable) -> None:
        pubsub = self.client.pubsub()
        pubsub.subscribe(**{channel: lambda msg: callback(msg)})
        thread = pubsub.run_in_thread(sleep_time=0.05, daemon=True)
        self._pubsub_threads.append((pubsub, thread))

    def close(self) -> None:
        for pubsub, thread in self._pubsub_threads:
            try:
                thread.stop()
            except Exception:
                pass
            try:
                pubsub.close()
            except Exception:
                pass
        self._pubsub_threads.clear()
        try:
            self.client.close()
        except Exception:
            pass
