from __future__ import annotations

from enum import StrEnum


class TestState(StrEnum):
    IDLE = "IDLE"
    PREPARING = "PREPARING"
    RUNNING = "RUNNING"
    STOPPING = "STOPPING"

