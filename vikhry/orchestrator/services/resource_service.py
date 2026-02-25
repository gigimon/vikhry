from __future__ import annotations

import time
from typing import Any

from vikhry.orchestrator.models.resource import CreateResourceResult
from vikhry.orchestrator.redis_repo.state_repo import TestStateRepository


class ResourceService:
    def __init__(
        self,
        state_repo: TestStateRepository,
        default_prepare_counts: dict[str, int] | None = None,
    ) -> None:
        self._state_repo = state_repo
        self._default_prepare_counts = default_prepare_counts or {}

    async def prepare_for_start(self, target_users: int) -> dict[str, Any]:
        created: dict[str, int] = {}
        for resource_name, count in self._default_prepare_counts.items():
            if count <= 0:
                continue
            result = await self.create_resources(
                resource_name=resource_name,
                count=count,
                payload={"source": "preparing", "target_users": target_users},
            )
            created[result.resource_name] = result.count
        return {"created": created, "target_users": target_users}

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

