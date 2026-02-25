from __future__ import annotations

from typing import Any

from vikhry.worker.redis_repo.state_repo import WorkerStateRepository


class WorkerVUResources:
    def __init__(self, state_repo: WorkerStateRepository) -> None:
        self._state_repo = state_repo

    async def acquire(self, resource_name: str) -> dict[str, Any]:
        payload = await self._state_repo.acquire_resource_data(resource_name)
        if payload is None:
            raise RuntimeError(f"resource pool `{resource_name}` is empty")
        return payload

    async def release(self, resource_name: str, resource_id: int | str) -> None:
        await self._state_repo.release_resource(resource_name, resource_id)

