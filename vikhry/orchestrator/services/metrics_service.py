from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

from vikhry.orchestrator.redis_repo.state_repo import TestStateRepository

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class _MetricBucket:
    second: int
    requests: int = 0
    errors: int = 0
    latency_sum_ms: float = 0.0
    latency_samples: int = 0


@dataclass(slots=True)
class _MetricState:
    last_event_id: str | None = None
    buckets: deque[_MetricBucket] = field(default_factory=deque)
    recent_events: deque[dict[str, Any]] = field(default_factory=deque)


class MetricsService:
    def __init__(
        self,
        state_repo: TestStateRepository,
        *,
        poll_interval_s: float = 1.0,
        window_s: int = 60,
        max_events_per_metric_per_poll: int = 300,
        max_recent_events_per_metric: int = 1000,
        max_subscriber_queue: int = 64,
    ) -> None:
        self._state_repo = state_repo
        self._poll_interval_s = poll_interval_s
        self._window_s = max(1, window_s)
        self._max_events_per_metric_per_poll = max(1, max_events_per_metric_per_poll)
        self._max_recent_events_per_metric = max(1, max_recent_events_per_metric)
        self._max_subscriber_queue = max(1, max_subscriber_queue)

        self._metrics: dict[str, _MetricState] = {}
        self._subscribers: dict[str, asyncio.Queue[dict[str, object]]] = {}
        self._metrics_with_backlog: set[str] = set()
        self._dropped_subscriber_messages = 0

        self._task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._task = asyncio.create_task(self._run_loop(), name="metrics-poller")

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
        async with self._lock:
            self._subscribers.clear()

    async def subscribe(self) -> tuple[str, asyncio.Queue[dict[str, object]]]:
        subscriber_id = str(uuid4())
        queue: asyncio.Queue[dict[str, object]] = asyncio.Queue(
            maxsize=self._max_subscriber_queue
        )
        async with self._lock:
            self._subscribers[subscriber_id] = queue
        return subscriber_id, queue

    async def unsubscribe(self, subscriber_id: str) -> None:
        async with self._lock:
            self._subscribers.pop(subscriber_id, None)

    async def get_metrics(
        self,
        metric_id: str | None = None,
        count: int = 100,
        include_events: bool = True,
    ) -> dict[str, object]:
        capped_count = max(0, min(count, self._max_recent_events_per_metric))
        known_metric_ids = await self._state_repo.list_metrics() if metric_id is None else [metric_id]
        async with self._lock:
            for known_metric_id in known_metric_ids:
                self._state_for(known_metric_id)
            return self._build_snapshot_locked(
                metric_id=metric_id,
                count=capped_count,
                include_events=include_events,
            )

    async def refresh_now(self) -> None:
        await self._poll_once()

    async def _run_loop(self) -> None:
        while True:
            try:
                await self._poll_once()
            except Exception:  # noqa: BLE001
                # Keep polling loop alive in degraded conditions.
                logger.exception("metrics poll loop failed")
            await asyncio.sleep(self._poll_interval_s)

    async def _poll_once(self) -> None:
        metric_ids = await self._state_repo.list_metrics()
        if not metric_ids:
            return

        async with self._lock:
            cursors = {
                metric_id: self._metrics.get(metric_id, _MetricState()).last_event_id
                for metric_id in metric_ids
            }

        fetched: dict[str, list[dict[str, Any]]] = {}
        backlog_metrics: set[str] = set()

        for metric_id in metric_ids:
            events = await self._state_repo.read_metric_events_after(
                metric_id=metric_id,
                after_event_id=cursors.get(metric_id),
                count=self._max_events_per_metric_per_poll,
            )
            if events:
                fetched[metric_id] = events
            if len(events) >= self._max_events_per_metric_per_poll:
                backlog_metrics.add(metric_id)

        if not fetched and not backlog_metrics:
            return

        async with self._lock:
            for metric_id, events in fetched.items():
                state = self._state_for(metric_id)
                for event in events:
                    state.last_event_id = event["event_id"]
                    state.recent_events.append(event)
                    while len(state.recent_events) > self._max_recent_events_per_metric:
                        state.recent_events.popleft()
                    self._apply_aggregate_event(state, event)

            self._metrics_with_backlog |= backlog_metrics
            for metric_id in list(self._metrics_with_backlog):
                if metric_id not in backlog_metrics:
                    self._metrics_with_backlog.discard(metric_id)

            payload = {
                "type": "metrics_tick",
                "payload": self._build_snapshot_locked(
                    metric_id=None,
                    count=100,
                    include_events=False,
                ),
            }
            self._fanout_locked(payload)

    def _state_for(self, metric_id: str) -> _MetricState:
        state = self._metrics.get(metric_id)
        if state is None:
            state = _MetricState(recent_events=deque(maxlen=self._max_recent_events_per_metric))
            self._metrics[metric_id] = state
        return state

    def _apply_aggregate_event(self, state: _MetricState, event: dict[str, Any]) -> None:
        event_id = event.get("event_id", "0-0")
        data = event.get("data")
        if not isinstance(data, dict):
            data = {}

        ts_ms = _extract_event_ts_ms(event_id, data)
        second = ts_ms // 1000

        bucket = self._ensure_bucket(state, second)
        bucket.requests += 1
        if _is_error_event(data):
            bucket.errors += 1

        latency_ms = _extract_latency_ms(data)
        if latency_ms is not None:
            bucket.latency_sum_ms += latency_ms
            bucket.latency_samples += 1

        self._trim_buckets(state, current_second=second)

    def _ensure_bucket(self, state: _MetricState, second: int) -> _MetricBucket:
        if state.buckets and state.buckets[-1].second == second:
            return state.buckets[-1]
        bucket = _MetricBucket(second=second)
        state.buckets.append(bucket)
        return bucket

    def _trim_buckets(self, state: _MetricState, current_second: int) -> None:
        min_second = current_second - self._window_s + 1
        while state.buckets and state.buckets[0].second < min_second:
            state.buckets.popleft()

    def _aggregate(self, state: _MetricState) -> dict[str, object]:
        if not state.buckets:
            return {
                "window_s": self._window_s,
                "requests": 0,
                "errors": 0,
                "error_rate": 0.0,
                "rps": 0.0,
                "latency_avg_ms": None,
            }

        requests = sum(bucket.requests for bucket in state.buckets)
        errors = sum(bucket.errors for bucket in state.buckets)
        latency_sum_ms = sum(bucket.latency_sum_ms for bucket in state.buckets)
        latency_samples = sum(bucket.latency_samples for bucket in state.buckets)

        return {
            "window_s": self._window_s,
            "requests": requests,
            "errors": errors,
            "error_rate": (errors / requests) if requests else 0.0,
            "rps": requests / self._window_s,
            "latency_avg_ms": (latency_sum_ms / latency_samples)
            if latency_samples
            else None,
        }

    def _build_snapshot_locked(
        self,
        metric_id: str | None,
        count: int,
        include_events: bool,
    ) -> dict[str, object]:
        metric_ids = [metric_id] if metric_id else sorted(self._metrics.keys())
        metrics_payload: list[dict[str, object]] = []

        for current_metric_id in metric_ids:
            state = self._metrics.get(current_metric_id)
            if state is None:
                metrics_payload.append(
                    {
                        "metric_id": current_metric_id,
                        "last_event_id": None,
                        "aggregate": {
                            "window_s": self._window_s,
                            "requests": 0,
                            "errors": 0,
                            "error_rate": 0.0,
                            "rps": 0.0,
                            "latency_avg_ms": None,
                        },
                        "events": [] if include_events else None,
                    }
                )
                continue

            events_payload: list[dict[str, Any]] | None = None
            if include_events:
                if count == 0:
                    events_payload = []
                else:
                    events_payload = list(state.recent_events)[-count:]

            metrics_payload.append(
                {
                    "metric_id": current_metric_id,
                    "last_event_id": state.last_event_id,
                    "aggregate": self._aggregate(state),
                    "events": events_payload,
                }
            )

        return {
            "generated_at": int(time.time()),
            "lag": {
                "detected": bool(self._metrics_with_backlog),
                "metrics_with_backlog": sorted(self._metrics_with_backlog),
                "dropped_subscriber_messages": self._dropped_subscriber_messages,
            },
            "metrics": metrics_payload,
            "count": count,
            "include_events": include_events,
        }

    def _fanout_locked(self, payload: dict[str, object]) -> None:
        for queue in self._subscribers.values():
            if queue.full():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                self._dropped_subscriber_messages += 1
            try:
                queue.put_nowait(payload)
            except asyncio.QueueFull:
                self._dropped_subscriber_messages += 1


def _extract_event_ts_ms(event_id: str, payload: dict[str, Any]) -> int:
    for key in ("timestamp_ms", "ts_ms"):
        value = payload.get(key)
        parsed = _to_int(value)
        if parsed is not None:
            return parsed

    for key in ("timestamp", "ts"):
        value = payload.get(key)
        parsed = _to_float(value)
        if parsed is None:
            continue
        if parsed < 10_000_000_000:
            return int(parsed * 1000)
        return int(parsed)

    # Stream event IDs are "<ms>-<seq>".
    head = event_id.split("-", maxsplit=1)[0]
    parsed_head = _to_int(head)
    if parsed_head is not None:
        return parsed_head

    return int(time.time() * 1000)


def _extract_latency_ms(payload: dict[str, Any]) -> float | None:
    for key in ("time", "latency_ms", "duration_ms", "latency", "duration"):
        parsed = _to_float(payload.get(key))
        if parsed is not None and parsed >= 0:
            return parsed
    return None


def _is_error_event(payload: dict[str, Any]) -> bool:
    status = payload.get("status")
    if isinstance(status, bool):
        return not status
    if isinstance(status, str):
        normalized = status.strip().lower()
        if normalized in {"ok", "success", "true", "1"}:
            return False
        if normalized in {"error", "failed", "false", "0"}:
            return True

    status_code = _to_int(payload.get("status_code"))
    if status_code is not None:
        return status_code >= 400

    error = payload.get("error")
    if isinstance(error, bool):
        return error
    if isinstance(error, (int, float)):
        return bool(error)
    if isinstance(error, str):
        return error.lower() not in {"", "0", "false", "none", "null"}

    for key in ("ok", "success"):
        value = payload.get(key)
        if isinstance(value, bool):
            return not value
        if isinstance(value, (int, float)):
            return value == 0
        if isinstance(value, str):
            return value.lower() in {"0", "false", "no"}

    return False


def _to_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _to_float(value: object) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None
