from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class CreateResourceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")
    count: int = Field(default=1, ge=1, le=100_000)
    payload: dict[str, Any] = Field(default_factory=dict)


class CreateResourceResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resource_name: str
    count: int
    resource_ids: list[str]


class EnsureResourceCountRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")
    count: int = Field(ge=0, le=100_000)
    payload: dict[str, Any] = Field(default_factory=dict)


class EnsureResourceCountResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resource_name: str
    target_count: int
    existing_count: int
    created_count: int
    current_count: int
    created_resource_ids: list[str]
