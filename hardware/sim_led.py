"""Simulated LED with off/on/blink states."""
from __future__ import annotations


class SimulatedLED:
    """Tracks LED state: off, on, or blink."""

    VALID_STATES = ("off", "on", "blink")

    def __init__(self, config: dict):
        self.id = config["id"]
        self.name = config["name"]
        self.color = config.get("color", "white")
        self.initial_state = config.get("initial_state", "off")
        if self.initial_state not in self.VALID_STATES:
            raise ValueError(f"Invalid initial LED state: {self.initial_state}")
        self.state = self.initial_state

    def set_state(self, state: str) -> None:
        if state not in self.VALID_STATES:
            raise ValueError(
                f"Invalid LED state '{state}'. Must be one of {self.VALID_STATES}"
            )
        self.state = state

    def get_state(self) -> str:
        return self.state

    def get_color(self) -> str:
        return self.color

    def get_info(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "color": self.color,
            "state": self.state,
        }

    def reset(self) -> None:
        self.state = self.initial_state
