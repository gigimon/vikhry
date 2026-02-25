from __future__ import annotations

import time
from typing import Any

from vikhry.orchestrator.models.resource import (
    CreateResourceResult,
    EnsureResourceCountResult,
)
from vikhry.orchestrator.redis_repo.state_repo import TestStateRepository


class ResourceService:
    def __init__(
        self,
        state_repo: TestStateRepository,
        scenario_resource_names: list[str] | None = None,
        default_prepare_counts: dict[str, int] | None = None,
    ) -> None:
        self._state_repo = state_repo
        self._scenario_resource_names = sorted(set(scenario_resource_names or []))
        self._default_prepare_counts = default_prepare_counts or {}

    async def prepare_for_start(self, target_users: int) -> dict[str, Any]:
        created: dict[str, int] = {}
        for resource_name, desired_count in self._default_prepare_counts.items():
            if desired_count < 0:
                continue
            result = await self.ensure_resource_count(
                resource_name=resource_name,
                target_count=desired_count,
                payload={
                    "source": "preparing",
                },
            )
            created[result.resource_name] = result.created_count
        return {
            "created": created,
            "target_users": target_users,
            "scenario_resources": list(self._scenario_resource_names),
            "mode": "manual",
        }

    async def ensure_resource_count(
        self,
        resource_name: str,
        target_count: int,
        payload: dict[str, Any] | None = None,
    ) -> EnsureResourceCountResult:
        if target_count < 0:
            raise ValueError("target_count must be >= 0")

        counters = await self._state_repo.list_resource_counters()
        existing_count = counters.get(resource_name, 0)
        count_to_create = max(0, target_count - existing_count)

        created_resource_ids: list[str] = []
        if count_to_create > 0:
            result = await self.create_resources(
                resource_name=resource_name,
                count=count_to_create,
                payload={
                    **(payload or {}),
                    "source": (payload or {}).get("source", "ensure_resource_count"),
                    "target_count": target_count,
                    "existing_count": existing_count,
                },
            )
            created_resource_ids = result.resource_ids

        current_count = existing_count + count_to_create
        return EnsureResourceCountResult(
            resource_name=resource_name,
            target_count=target_count,
            existing_count=existing_count,
            created_count=count_to_create,
            current_count=current_count,
            created_resource_ids=created_resource_ids,
        )

    async def create_resources(
        self,
        resource_name: str,
        count: int,
        payload: dict[str, Any] | None = None,
    ) -> CreateResourceResult:
        payload = payload or {}
        resource_ids: list[str] = []
        created_at = self._now_ts()

        for _ in range(count):
            next_id = await self._state_repo.increment_resource_counter(resource_name, delta=1)
            resource_id = str(next_id)
            await self._state_repo.set_resource_data(
                resource_name=resource_name,
                resource_id=resource_id,
                payload={
                    **payload,
                    "resource_name": resource_name,
                    "resource_id": resource_id,
                    "created_at": created_at,
                },
            )
            resource_ids.append(resource_id)

        return CreateResourceResult(
            resource_name=resource_name,
            count=count,
            resource_ids=resource_ids,
        )

    async def counters(self) -> dict[str, int]:
        return await self._state_repo.list_resource_counters()

    @staticmethod
    def _now_ts() -> int:
        return int(time.time())
