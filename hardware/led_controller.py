"""LED GPIO controller

Will be implemented when ESP hardware is integrated (Session 14).
Until then, use HardwareManager with mode: simulated.
"""
from __future__ import annotations


class LEDController:
    """Stub for real-hardware LED GPIO controller. Not yet implemented."""

    def __init__(self, *args, **kwargs):
        raise NotImplementedError(
            "LEDController will be implemented when ESP hardware is integrated. "
            "Use HardwareManager with mode: simulated for now."
        )
