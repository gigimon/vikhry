from __future__ import annotations

import asyncio
import time
from collections.abc import Callable

from vikhry.orchestrator.models.worker import WorkerHealthStatus
from vikhry.orchestrator.redis_repo.state_repo import TestStateRepository


class NoAliveWorkersError(RuntimeError):
    """Raised when operation requires at least one alive worker."""


class WorkerPresenceService:
    def __init__(
        self,
        state_repo: TestStateRepository,
        heartbeat_timeout_s: int,
        now_fn: Callable[[], float] | None = None,
    ) -> None:
        self._state_repo = state_repo
        self._heartbeat_timeout_s = heartbeat_timeout_s
        self._now_fn = now_fn or time.time
        self._cached_alive_workers: tuple[str, ...] = ()
        self._last_scan_ts: int | None = None

    async def refresh_cache(self) -> list[str]:
        alive = await self.list_alive_workers()
        self._cached_alive_workers = tuple(alive)
        self._last_scan_ts = self.now_ts()
        return alive

    async def list_alive_workers(self) -> list[str]:
        workers = await self._state_repo.list_workers()
        if not workers:
            return []

        statuses = await asyncio.gather(
            *(self._state_repo.get_worker_status(worker_id) for worker_id in workers)
        )
        now_ts = self.now_ts()
        alive_workers: list[str] = []

        for worker_id, status in zip(workers, statuses, strict=True):
            if status is None:
                continue
            if status.status != WorkerHealthStatus.HEALTHY:
                continue
            if (now_ts - status.last_heartbeat) > self._heartbeat_timeout_s:
                continue
            alive_workers.append(worker_id)

        # workers list is already sorted in repository; keep this deterministic order.
        return alive_workers

    async def require_alive_workers(self) -> list[str]:
        alive_workers = await self.refresh_cache()
        if alive_workers:
            return alive_workers
        raise NoAliveWorkersError(
            "No alive workers detected: require status=healthy and fresh heartbeat"
        )

    def cached_alive_workers(self) -> list[str]:
        return list(self._cached_alive_workers)

    def last_scan_ts(self) -> int | None:
        return self._last_scan_ts

    def now_ts(self) -> int:
        return int(self._now_fn())

