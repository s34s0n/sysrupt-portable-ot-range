"""Simulated relay with debounce and cycle counting."""
from __future__ import annotations

import logging
import time

log = logging.getLogger(__name__)


class SimulatedRelay:
    """Tracks relay on/off state with cycle counting and debounce."""

    MIN_TOGGLE_INTERVAL_S = 0.1  # 100ms debounce

    def __init__(self, config: dict):
        self.id = config["id"]
        self.name = config["name"]
        self.initial_state = bool(config.get("initial_state", False))
        self.click_sound = bool(config.get("click_sound", False))
        self.state = self.initial_state
        self.total_cycles = 0
        self.last_change: float | None = None

    def set_state(self, on: bool) -> dict | None:
        on = bool(on)
        now = time.time()
        if self.last_change is not None and (now - self.last_change) < self.MIN_TOGGLE_INTERVAL_S:
            log.warning(
                "Relay %s debounce: ignoring toggle within %.3fs",
                self.id,
                self.MIN_TOGGLE_INTERVAL_S,
            )
            return None
        if on == self.state:
            return None
        self.state = on
        self.total_cycles += 1
        self.last_change = now
        return {
            "relay_id": self.id,
            "state": self.state,
            "timestamp": now,
            "total_cycles": self.total_cycles,
        }

    def get_state(self) -> bool:
        return self.state

    def get_info(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "state": self.state,
            "total_cycles": self.total_cycles,
            "last_change": self.last_change,
        }

    def reset(self) -> None:
        self.state = self.initial_state
        self.total_cycles = 0
        self.last_change = None
