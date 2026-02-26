from __future__ import annotations

import asyncio
import logging
import os
import resource
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass

from vikhry.orchestrator.models.worker import WorkerHealthStatus
from vikhry.worker.redis_repo.state_repo import WorkerStateRepository

logger = logging.getLogger(__name__)


class WorkerHeartbeatService:
    def __init__(
        self,
        state_repo: WorkerStateRepository,
        *,
        worker_id: str,
        interval_s: float,
        now_fn: Callable[[], float] | None = None,
    ) -> None:
        self._state_repo = state_repo
        self._worker_id = worker_id
        self._interval_s = max(0.1, interval_s)
        self._now_fn = now_fn or time.time
        self._stats_sampler = _RuntimeStatsSampler(now_fn=self._now_fn)
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._task = asyncio.create_task(self._run(), name=f"worker-heartbeat:{self._worker_id}")

    async def stop(self) -> None:
        if not self._task:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        finally:
            self._task = None

    async def mark_healthy(self) -> None:
        await self._publish(status=WorkerHealthStatus.HEALTHY)

    async def mark_unhealthy(self) -> None:
        await self._publish(status=WorkerHealthStatus.UNHEALTHY)

    async def _run(self) -> None:
        while True:
            try:
                await self.mark_healthy()
            except Exception:  # noqa: BLE001
                logger.exception("heartbeat update failed (worker_id=%s)", self._worker_id)
            await asyncio.sleep(self._interval_s)

    async def _publish(self, *, status: WorkerHealthStatus) -> None:
        sample = self._stats_sampler.sample()
        await self._state_repo.set_worker_health(
            self._worker_id,
            status=status,
            last_heartbeat=int(self._now_fn()),
            cpu_percent=sample.cpu_percent,
            rss_bytes=sample.rss_bytes,
            memory_percent=sample.memory_percent,
        )


@dataclass(slots=True, frozen=True)
class RuntimeSample:
    cpu_percent: float
    rss_bytes: int
    memory_percent: float | None


class _RuntimeStatsSampler:
    def __init__(self, now_fn: Callable[[], float]) -> None:
        self._now_fn = now_fn
        self._prev_wall_ts: float | None = None
        self._prev_cpu_time: float | None = None
        self._rss_divisor = 1024 if sys.platform.startswith("linux") else 1
        self._total_memory_bytes = _total_memory_bytes()

    def sample(self) -> RuntimeSample:
        wall_ts = float(self._now_fn())
        cpu_time = _process_cpu_time()

        cpu_percent = 0.0
        if self._prev_wall_ts is not None and self._prev_cpu_time is not None:
            wall_delta = wall_ts - self._prev_wall_ts
            cpu_delta = cpu_time - self._prev_cpu_time
            if wall_delta > 0 and cpu_delta >= 0:
                cpu_percent = max(0.0, (cpu_delta / wall_delta) * 100.0)

        self._prev_wall_ts = wall_ts
        self._prev_cpu_time = cpu_time

        ru = resource.getrusage(resource.RUSAGE_SELF)
        rss_bytes = int(max(0, int(ru.ru_maxrss)) * self._rss_divisor)

        memory_percent: float | None = None
        if self._total_memory_bytes and self._total_memory_bytes > 0:
            memory_percent = max(0.0, (rss_bytes / self._total_memory_bytes) * 100.0)

        return RuntimeSample(
            cpu_percent=cpu_percent,
            rss_bytes=rss_bytes,
            memory_percent=memory_percent,
        )


def _process_cpu_time() -> float:
    times = os.times()
    return float(times.user + times.system)


def _total_memory_bytes() -> int | None:
    if not hasattr(os, "sysconf"):
        return None
    try:
        page_size = int(os.sysconf("SC_PAGE_SIZE"))
        pages = int(os.sysconf("SC_PHYS_PAGES"))
    except (ValueError, OSError):
        return None
    if page_size <= 0 or pages <= 0:
        return None
    return page_size * pages
