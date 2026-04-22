from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class StartTestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_users: int = Field(ge=0)
    init_params: dict[str, Any] = Field(default_factory=dict)
    spawn_interval_ms: int = Field(default=0, ge=0, le=60_000)


class ChangeUsersRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_users: int = Field(ge=0)
    spawn_interval_ms: int = Field(default=0, ge=0, le=60_000)
