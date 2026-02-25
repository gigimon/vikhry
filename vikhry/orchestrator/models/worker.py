from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class WorkerHealthStatus(StrEnum):
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"


class WorkerStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: WorkerHealthStatus
    last_heartbeat: int = Field(ge=0)

