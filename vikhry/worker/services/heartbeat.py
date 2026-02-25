from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable

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
        await self._state_repo.set_worker_health(
            self._worker_id,
            status=status,
            last_heartbeat=int(self._now_fn()),
        )
