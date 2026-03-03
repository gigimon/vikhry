from __future__ import annotations

import asyncio
import logging
import math
import time
from collections import deque
from collections.abc import Iterable
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
    fatal_count: int = 0
    latency_sum_ms: float = 0.0
    latency_samples: int = 0
    latencies_ms: list[float] = field(default_factory=list)
    result_code_counts: dict[str, int] = field(default_factory=dict)
    result_category_counts: dict[str, int] = field(default_factory=dict)


@dataclass(slots=True)
class _MetricState:
    last_event_id: str | None = None
    buckets: deque[_MetricBucket] = field(default_factory=deque)
    recent_events: deque[dict[str, Any]] = field(default_factory=deque)
    total_requests: int = 0
    total_errors: int = 0
    total_fatal_count: int = 0
    total_latency_sum_ms: float = 0.0
    total_latency_samples: int = 0
    total_latencies_ms: list[float] = field(default_factory=list)
    total_result_code_counts: dict[str, int] = field(default_factory=dict)
    total_result_category_counts: dict[str, int] = field(default_factory=dict)


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
        max_result_codes: int = 10,
    ) -> None:
        self._state_repo = state_repo
        self._poll_interval_s = poll_interval_s
        self._window_s = max(1, window_s)
        self._max_events_per_metric_per_poll = max(1, max_events_per_metric_per_poll)
        self._max_recent_events_per_metric = max(1, max_recent_events_per_metric)
        self._max_subscriber_queue = max(1, max_subscriber_queue)
        self._max_result_codes = max(1, max_result_codes)

        self._metrics: dict[str, _MetricState] = {}
        self._subscribers: dict[str, asyncio.Queue[dict[str, object]]] = {}
        self._metrics_with_backlog: set[str] = set()
        self._dropped_subscriber_messages = 0
        self._run_started_at_ms: int | None = None

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
        if metric_id is None:
            try:
                known_metric_ids = await self._state_repo.list_metrics()
            except Exception:  # noqa: BLE001
                # Degrade gracefully for API consumers if Redis metrics index is unavailable
                # or has incompatible type from legacy data.
                logger.exception("failed to list metrics from state repo; returning cached snapshot")
                known_metric_ids = []
        else:
            known_metric_ids = [metric_id]
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

    async def reset_for_new_run(self) -> None:
        deleted_keys = await self._state_repo.clear_metrics_data()
        async with self._lock:
            self._metrics.clear()
            self._metrics_with_backlog.clear()
            self._dropped_subscriber_messages = 0
            self._run_started_at_ms = None
        logger.info("metrics reset for new run deleted_keys=%s", deleted_keys)

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
        if self._run_started_at_ms is None:
            self._run_started_at_ms = ts_ms

        bucket = self._ensure_bucket(state, second)
        bucket.requests += 1
        state.total_requests += 1
        if _is_error_event(data):
            bucket.errors += 1
            state.total_errors += 1

        result_code = _extract_result_code(data)
        if result_code is not None:
            _increment_counter(bucket.result_code_counts, result_code)
            _increment_counter(state.total_result_code_counts, result_code)

        result_category = _extract_result_category(data)
        if result_category is not None:
            _increment_counter(bucket.result_category_counts, result_category)
            _increment_counter(state.total_result_category_counts, result_category)

        if _is_fatal_event(data):
            bucket.fatal_count += 1
            state.total_fatal_count += 1

        latency_ms = _extract_latency_ms(data)
        if latency_ms is not None:
            bucket.latency_sum_ms += latency_ms
            bucket.latency_samples += 1
            bucket.latencies_ms.append(latency_ms)
            state.total_latency_sum_ms += latency_ms
            state.total_latency_samples += 1
            state.total_latencies_ms.append(latency_ms)

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
            return self._empty_aggregate()

        requests = sum(bucket.requests for bucket in state.buckets)
        errors = sum(bucket.errors for bucket in state.buckets)
        latency_sum_ms = sum(bucket.latency_sum_ms for bucket in state.buckets)
        latency_samples = sum(bucket.latency_samples for bucket in state.buckets)
        latencies_ms = sorted(
            latency for bucket in state.buckets for latency in bucket.latencies_ms
        )
        fatal_count = sum(bucket.fatal_count for bucket in state.buckets)
        result_code_counts = _merge_counts(bucket.result_code_counts for bucket in state.buckets)
        result_category_counts = _merge_counts(
            bucket.result_category_counts for bucket in state.buckets
        )
        limited_result_codes = _limit_counts(
            result_code_counts,
            top_k=self._max_result_codes,
        )

        return {
            "window_s": self._window_s,
            "requests": requests,
            "errors": errors,
            "error_rate": (errors / requests) if requests else 0.0,
            "rps": requests / self._window_s,
            "latency_avg_ms": (latency_sum_ms / latency_samples)
            if latency_samples
            else None,
            "latency_median_ms": _sorted_median(latencies_ms),
            "latency_p95_ms": _sorted_percentile_nearest_rank(latencies_ms, percentile=95),
            "latency_p99_ms": _sorted_percentile_nearest_rank(latencies_ms, percentile=99),
            "result_code_counts": limited_result_codes,
            "result_category_counts": _sort_counts(result_category_counts),
            "fatal_count": fatal_count,
            "top_result_codes": _to_top_result_codes(limited_result_codes),
        }

    def _aggregate_total(self, state: _MetricState, now_ms: int) -> dict[str, object]:
        elapsed_s = _elapsed_total_window_s(now_ms=now_ms, started_at_ms=self._run_started_at_ms)
        total_latencies_ms = sorted(state.total_latencies_ms)
        limited_result_codes = _limit_counts(
            state.total_result_code_counts,
            top_k=self._max_result_codes,
        )

        return {
            "window_s": elapsed_s,
            "requests": state.total_requests,
            "errors": state.total_errors,
            "error_rate": (state.total_errors / state.total_requests)
            if state.total_requests
            else 0.0,
            "rps": (state.total_requests / elapsed_s) if elapsed_s > 0 else 0.0,
            "latency_avg_ms": (state.total_latency_sum_ms / state.total_latency_samples)
            if state.total_latency_samples
            else None,
            "latency_median_ms": _sorted_median(total_latencies_ms),
            "latency_p95_ms": _sorted_percentile_nearest_rank(total_latencies_ms, percentile=95),
            "latency_p99_ms": _sorted_percentile_nearest_rank(total_latencies_ms, percentile=99),
            "result_code_counts": limited_result_codes,
            "result_category_counts": _sort_counts(state.total_result_category_counts),
            "fatal_count": state.total_fatal_count,
            "top_result_codes": _to_top_result_codes(limited_result_codes),
        }

    def _build_snapshot_locked(
        self,
        metric_id: str | None,
        count: int,
        include_events: bool,
    ) -> dict[str, object]:
        now_ms = int(time.time() * 1000)
        metric_ids = [metric_id] if metric_id else sorted(self._metrics.keys())
        metrics_payload: list[dict[str, object]] = []

        for current_metric_id in metric_ids:
            state = self._metrics.get(current_metric_id)
            if state is None:
                metrics_payload.append(
                    {
                        "metric_id": current_metric_id,
                        "last_event_id": None,
                        "aggregate": self._empty_aggregate(),
                        "aggregate_total": self._empty_aggregate(
                            window_s=_elapsed_total_window_s(
                                now_ms=now_ms,
                                started_at_ms=self._run_started_at_ms,
                            )
                        ),
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
                    "aggregate_total": self._aggregate_total(state, now_ms),
                    "events": events_payload,
                }
            )

        return {
            "generated_at": int(now_ms / 1000),
            "lag": {
                "detected": bool(self._metrics_with_backlog),
                "metrics_with_backlog": sorted(self._metrics_with_backlog),
                "dropped_subscriber_messages": self._dropped_subscriber_messages,
            },
            "metrics": metrics_payload,
            "count": count,
            "include_events": include_events,
        }

    def _empty_aggregate(self, *, window_s: int | None = None) -> dict[str, object]:
        return {
            "window_s": self._window_s if window_s is None else max(1, int(window_s)),
            "requests": 0,
            "errors": 0,
            "error_rate": 0.0,
            "rps": 0.0,
            "latency_avg_ms": None,
            "latency_median_ms": None,
            "latency_p95_ms": None,
            "latency_p99_ms": None,
            "result_code_counts": {},
            "result_category_counts": {},
            "fatal_count": 0,
            "top_result_codes": [],
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


def _elapsed_total_window_s(*, now_ms: int, started_at_ms: int | None) -> int:
    if started_at_ms is None:
        return 1
    return max(1, int((now_ms - started_at_ms) / 1000))


def _sorted_median(sorted_values: list[float]) -> float | None:
    if not sorted_values:
        return None
    size = len(sorted_values)
    middle = size // 2
    if size % 2:
        return sorted_values[middle]
    return (sorted_values[middle - 1] + sorted_values[middle]) / 2.0


def _sorted_percentile_nearest_rank(
    sorted_values: list[float],
    *,
    percentile: int,
) -> float | None:
    if not sorted_values:
        return None
    if percentile <= 0:
        return sorted_values[0]
    if percentile >= 100:
        return sorted_values[-1]

    rank = math.ceil((percentile / 100) * len(sorted_values))
    index = max(0, min(rank - 1, len(sorted_values) - 1))
    return sorted_values[index]


def _extract_latency_ms(payload: dict[str, Any]) -> float | None:
    parsed = _to_float(payload.get("time"))
    if parsed is not None and parsed >= 0:
        return parsed
    return None


def _extract_result_code(payload: dict[str, Any]) -> str | None:
    value = payload.get("result_code")
    if isinstance(value, str):
        normalized = value.strip()
        if normalized:
            return normalized
    return None


def _extract_result_category(payload: dict[str, Any]) -> str | None:
    value = payload.get("result_category")
    if isinstance(value, str):
        normalized = value.strip()
        if normalized:
            return normalized
    return None


def _is_error_event(payload: dict[str, Any]) -> bool:
    status = payload.get("status")
    if isinstance(status, bool):
        return not status
    return False


def _is_fatal_event(payload: dict[str, Any]) -> bool:
    fatal = payload.get("fatal")
    if isinstance(fatal, bool):
        return fatal
    return False


def _increment_counter(target: dict[str, int], key: str) -> None:
    target[key] = target.get(key, 0) + 1


def _merge_counts(items: Iterable[dict[str, int]]) -> dict[str, int]:
    merged: dict[str, int] = {}
    for entry in items:
        for key, value in entry.items():
            merged[key] = merged.get(key, 0) + int(value)
    return merged


def _sort_counts(counts: dict[str, int]) -> dict[str, int]:
    sorted_items = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return {key: value for key, value in sorted_items}


def _limit_counts(counts: dict[str, int], *, top_k: int) -> dict[str, int]:
    if len(counts) <= top_k:
        return _sort_counts(counts)

    sorted_items = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    top_items = sorted_items[:top_k]
    other_count = sum(value for _, value in sorted_items[top_k:])
    limited = {key: value for key, value in top_items}
    if other_count > 0:
        limited["OTHER"] = other_count
    return limited


def _to_top_result_codes(result_code_counts: dict[str, int]) -> list[dict[str, object]]:
    return [
        {"result_code": result_code, "count": count}
        for result_code, count in result_code_counts.items()
    ]


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
