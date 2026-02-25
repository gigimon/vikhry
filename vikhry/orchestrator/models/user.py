from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class UserRuntimeStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"


class UserAssignment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: int | str
    worker_id: str = Field(min_length=1)
    status: UserRuntimeStatus = UserRuntimeStatus.PENDING
    updated_at: int = Field(ge=0)

