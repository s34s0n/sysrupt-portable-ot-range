"""GPIO manager

Will be implemented when ESP hardware is integrated (Session 14).
Until then, use HardwareManager with mode: simulated.
"""
from __future__ import annotations


class GPIOManager:
    """Stub for real-hardware GPIO manager. Not yet implemented."""

    def __init__(self, *args, **kwargs):
        raise NotImplementedError(
            "GPIOManager will be implemented when ESP hardware is integrated. "
            "Use HardwareManager with mode: simulated for now."
        )
