"""State manager - wraps Redis as a typed key/value state store."""

import json
import logging
from typing import Any, Dict, Optional

import redis

log = logging.getLogger("state")


class StateManager:
    """Read/write OT Range state in Redis."""

    def __init__(self, host: str = "127.0.0.1", port: int = 6379, db: int = 0):
        self.host = host
        self.port = port
        self.db = db
        self._r = redis.Redis(host=host, port=port, db=db,
                               decode_responses=True, socket_timeout=3.0)

    def get(self, key: str) -> Optional[Any]:
        """Get a value from Redis. Tries JSON parse, falls back to string."""
        raw = self._r.get(key)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return raw

    def set(self, key: str, value: Any):
        """Set a value in Redis. Non-string values are JSON-encoded."""
        if isinstance(value, str):
            self._r.set(key, value)
        else:
            self._r.set(key, json.dumps(value))

    def delete(self, key: str) -> int:
        """Delete a key."""
        return self._r.delete(key)

    def exists(self, key: str) -> bool:
        """Check if a key exists."""
        return self._r.exists(key) > 0

    def keys(self, pattern: str = "*") -> list:
        """Return keys matching a pattern."""
        return self._r.keys(pattern)

    def get_all(self) -> Dict[str, Any]:
        """Return all OT Range state as a dict (ctf:*, ids:*, physics:*)."""
        result = {}
        for prefix in ("ctf:", "ids:", "physics:", "hw:"):
            for key in self._r.keys(f"{prefix}*"):
                result[key] = self.get(key)
        return result

    def flush_pattern(self, pattern: str) -> int:
        """Delete all keys matching a glob pattern. Returns count deleted."""
        keys = self._r.keys(pattern)
        if keys:
            return self._r.delete(*keys)
        return 0
