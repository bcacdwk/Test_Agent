"""Session state definitions for instrument execution."""

from enum import StrEnum


class InstrumentState(StrEnum):
    """High-level B1500A session states."""

    DISCONNECTED = "disconnected"
    CONNECTED = "connected"
    IDLE_SAFE = "idle_safe"
    CONFIGURED = "configured"
    RUNNING = "running"
    FAULT = "fault"
    RECOVERING = "recovering"
