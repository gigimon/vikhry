from __future__ import annotations

import asyncio

import pytest

from vikhry.orchestrator.models.worker import WorkerHealthStatus
from vikhry.worker.services.heartbeat import WorkerHeartbeatService


class _FakeWorkerStateRepo:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    async def set_worker_health(
        self,
        worker_id: str,
        *,
        status: WorkerHealthStatus,
        last_heartbeat: int,
        cpu_percent: float | None = None,
        rss_bytes: int | None = None,
        memory_percent: float | None = None,
    ) -> None:
        self.calls.append(
            {
                "worker_id": worker_id,
                "status": status,
                "last_heartbeat": last_heartbeat,
                "cpu_percent": cpu_percent,
                "rss_bytes": rss_bytes,
                "memory_percent": memory_percent,
            }
        )


@pytest.mark.asyncio
async def test_heartbeat_mark_healthy_unhealthy_spec() -> None:
    ticks = iter([100.0, 100.0, 101.0, 101.0])
    repo = _FakeWorkerStateRepo()
    service = WorkerHeartbeatService(
        repo,  # type: ignore[arg-type]
        worker_id="w1",
        interval_s=1.0,
        now_fn=lambda: next(ticks),
    )

    await service.mark_healthy()
    await service.mark_unhealthy()

    assert [call["worker_id"] for call in repo.calls] == ["w1", "w1"]
    assert [call["status"] for call in repo.calls] == [
        WorkerHealthStatus.HEALTHY,
        WorkerHealthStatus.UNHEALTHY,
    ]
    assert [call["last_heartbeat"] for call in repo.calls] == [100, 101]
    assert all(isinstance(call["cpu_percent"], float) for call in repo.calls)
    assert all(isinstance(call["rss_bytes"], int) for call in repo.calls)
    assert all(call["memory_percent"] is None or isinstance(call["memory_percent"], float) for call in repo.calls)


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
    assert all(call["status"] is WorkerHealthStatus.HEALTHY for call in repo.calls)
    assert all(isinstance(call["cpu_percent"], float) for call in repo.calls)
    assert all(isinstance(call["rss_bytes"], int) for call in repo.calls)
