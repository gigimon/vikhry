from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class WorkerPhase(StrEnum):
    IDLE = "IDLE"
    RUNNING = "RUNNING"
    STOPPING = "STOPPING"


@dataclass(slots=True)
class WorkerRuntimeState:
    phase: WorkerPhase = WorkerPhase.IDLE
    current_epoch: int = 0
    init_params: dict[str, Any] = field(default_factory=dict)
    assigned_users: set[str] = field(default_factory=set)
    user_tasks: dict[str, asyncio.Task[None]] = field(default_factory=dict, repr=False)
