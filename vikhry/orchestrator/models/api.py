from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class StartTestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_users: int = Field(ge=0)


class ChangeUsersRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_users: int = Field(ge=0)

