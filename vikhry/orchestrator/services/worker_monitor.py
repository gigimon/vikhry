from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable

logger = logging.getLogger(__name__)


class WorkerMonitor:
    def __init__(
        self,
        scan_interval_s: int,
        heartbeat_timeout_s: int,
        on_tick: Callable[[], Awaitable[None] | None] | None = None,
    ) -> None:
        self._scan_interval_s = scan_interval_s
        self._heartbeat_timeout_s = heartbeat_timeout_s
        self._on_tick = on_tick
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._task = asyncio.create_task(self._run(), name="worker-monitor")

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

    async def _run(self) -> None:
        logger.info(
            "worker monitor started (scan_interval=%ss, heartbeat_timeout=%ss)",
            self._scan_interval_s,
            self._heartbeat_timeout_s,
        )
        while True:
            try:
                if self._on_tick:
                    maybe_awaitable = self._on_tick()
                    if maybe_awaitable is not None:
                        await maybe_awaitable
            except Exception:  # noqa: BLE001
                logger.exception("worker monitor tick failed")
            await asyncio.sleep(self._scan_interval_s)
