from __future__ import annotations

import logging
import time
from typing import Any

from vikhry.runtime.metrics import MetricEmitter
from vikhry.worker.redis_repo.state_repo import WorkerStateRepository

logger = logging.getLogger(__name__)


class WorkerMetricsPublisher:
    def __init__(
        self,
        state_repo: WorkerStateRepository,
        *,
        worker_id: str,
        metric_id: str,
    ) -> None:
        self._state_repo = state_repo
        self._worker_id = worker_id
        self._metric_id = metric_id

    def bind_user(self, user_id: str) -> MetricEmitter:
        async def _emit(metric: dict[str, Any]) -> None:
            await self.emit_for_user(user_id, metric)

        return _emit

    async def emit_for_user(self, user_id: str, metric: dict[str, Any]) -> None:
        payload = {
            "ts_ms": int(time.time() * 1000),
            "worker_id": self._worker_id,
            "user_id": user_id,
            **metric,
        }
        try:
            await self._state_repo.append_metric_event(self._metric_id, payload)
        except Exception:  # noqa: BLE001
            logger.exception(
                "failed to publish worker metric (worker_id=%s, metric_id=%s)",
                self._worker_id,
                self._metric_id,
            )
