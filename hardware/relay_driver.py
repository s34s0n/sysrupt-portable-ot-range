"""relay GPIO driver

Will be implemented when ESP hardware is integrated (Session 14).
Until then, use HardwareManager with mode: simulated.
"""
from __future__ import annotations


class RelayDriver:
    """Stub for real-hardware relay GPIO driver. Not yet implemented."""

    def __init__(self, *args, **kwargs):
        raise NotImplementedError(
            "RelayDriver will be implemented when ESP hardware is integrated. "
            "Use HardwareManager with mode: simulated for now."
        )
