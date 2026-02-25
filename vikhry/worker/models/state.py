from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import StrEnum


class WorkerPhase(StrEnum):
    IDLE = "IDLE"
    RUNNING = "RUNNING"
    STOPPING = "STOPPING"


@dataclass(slots=True)
class WorkerRuntimeState:
    phase: WorkerPhase = WorkerPhase.IDLE
    current_epoch: int = 0
    assigned_users: set[str] = field(default_factory=set)
    user_tasks: dict[str, asyncio.Task[None]] = field(default_factory=dict, repr=False)
