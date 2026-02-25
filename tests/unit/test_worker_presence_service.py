from __future__ import annotations

import pytest

from vikhry.orchestrator.models.worker import WorkerStatus
from vikhry.orchestrator.services.worker_presence import (
    NoAliveWorkersError,
    WorkerPresenceService,
)


class _FakeStateRepo:
    def __init__(self) -> None:
        self._workers = ["w1", "w2", "w3"]
        self._statuses = {
            "w1": WorkerStatus(status="healthy", last_heartbeat=100),
            "w2": WorkerStatus(status="healthy", last_heartbeat=10),
            "w3": WorkerStatus(status="unhealthy", last_heartbeat=100),
        }

    async def list_workers(self) -> list[str]:
        return sorted(self._workers)

    async def get_worker_status(self, worker_id: str) -> WorkerStatus | None:
        return self._statuses.get(worker_id)


@pytest.mark.asyncio
async def test_worker_presence_filters_by_health_and_heartbeat_spec() -> None:
    service = WorkerPresenceService(
        state_repo=_FakeStateRepo(),  # type: ignore[arg-type]
        heartbeat_timeout_s=15,
        now_fn=lambda: 110,
    )

    alive = await service.list_alive_workers()
    assert alive == ["w1"]


@pytest.mark.asyncio
async def test_worker_presence_raises_when_no_alive_workers_spec() -> None:
    service = WorkerPresenceService(
        state_repo=_FakeStateRepo(),  # type: ignore[arg-type]
        heartbeat_timeout_s=1,
        now_fn=lambda: 1_000,
    )

    with pytest.raises(NoAliveWorkersError):
        await service.require_alive_workers()

