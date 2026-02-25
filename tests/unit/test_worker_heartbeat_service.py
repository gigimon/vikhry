from __future__ import annotations

import asyncio

import pytest

from vikhry.orchestrator.models.worker import WorkerHealthStatus
from vikhry.worker.services.heartbeat import WorkerHeartbeatService


class _FakeWorkerStateRepo:
    def __init__(self) -> None:
        self.calls: list[tuple[str, WorkerHealthStatus, int]] = []

    async def set_worker_health(
        self,
        worker_id: str,
        *,
        status: WorkerHealthStatus,
        last_heartbeat: int,
    ) -> None:
        self.calls.append((worker_id, status, last_heartbeat))


@pytest.mark.asyncio
async def test_heartbeat_mark_healthy_unhealthy_spec() -> None:
    ticks = iter([100.0, 101.0])
    repo = _FakeWorkerStateRepo()
    service = WorkerHeartbeatService(
        repo,  # type: ignore[arg-type]
        worker_id="w1",
        interval_s=1.0,
        now_fn=lambda: next(ticks),
    )

    await service.mark_healthy()
    await service.mark_unhealthy()

    assert repo.calls == [
        ("w1", WorkerHealthStatus.HEALTHY, 100),
        ("w1", WorkerHealthStatus.UNHEALTHY, 101),
    ]


@pytest.mark.asyncio
async def test_heartbeat_loop_publishes_repeated_updates_spec() -> None:
    current = 200.0

    def now_fn() -> float:
        nonlocal current
        current += 1.0
        return current

    repo = _FakeWorkerStateRepo()
    service = WorkerHeartbeatService(
        repo,  # type: ignore[arg-type]
        worker_id="w-loop",
        interval_s=0.05,
        now_fn=now_fn,
    )

    await service.start()
    await asyncio.sleep(0.16)
    await service.stop()

    assert len(repo.calls) >= 2
    assert all(status is WorkerHealthStatus.HEALTHY for _, status, _ in repo.calls)
