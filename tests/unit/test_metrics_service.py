from __future__ import annotations

from typing import Any

import pytest

from vikhry.orchestrator.services.metrics_service import MetricsService


class _FakeStateRepo:
    def __init__(self, events_by_metric: dict[str, list[dict[str, Any]]]) -> None:
        self._events_by_metric = {
            metric_id: list(events) for metric_id, events in events_by_metric.items()
        }

    async def list_metrics(self) -> list[str]:
        return sorted(self._events_by_metric)

    async def read_metric_events_after(
        self,
        metric_id: str,
        after_event_id: str | None,
        count: int = 100,
    ) -> list[dict[str, Any]]:
        events = self._events_by_metric.get(metric_id, [])
        if after_event_id is None:
            start_index = 0
        else:
            start_index = 0
            for index, event in enumerate(events):
                if event["event_id"] == after_event_id:
                    start_index = index + 1
                    break
            else:
                start_index = len(events)
        return events[start_index : start_index + count]


def _metric_events(latencies: list[float], *, start_ts_ms: int = 1_700_000_000_000) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for index, latency in enumerate(latencies):
        ts_ms = start_ts_ms + index
        events.append(
            {
                "event_id": f"{ts_ms}-{index}",
                "data": {
                    "ts_ms": ts_ms,
                    "status": True,
                    "time": latency,
                },
            }
        )
    return events


@pytest.mark.asyncio
async def test_metrics_service_percentiles_for_odd_sample_size_spec() -> None:
    service = MetricsService(
        state_repo=_FakeStateRepo({"m1": _metric_events([10, 20, 30, 40, 50])}),  # type: ignore[arg-type]
        window_s=60,
    )

    await service.refresh_now()
    snapshot = await service.get_metrics(metric_id="m1", include_events=False)
    aggregate = snapshot["metrics"][0]["aggregate"]

    assert aggregate["latency_avg_ms"] == 30.0
    assert aggregate["latency_median_ms"] == 30.0
    assert aggregate["latency_p95_ms"] == 50.0
    assert aggregate["latency_p99_ms"] == 50.0


@pytest.mark.asyncio
async def test_metrics_service_percentiles_for_even_sample_size_spec() -> None:
    service = MetricsService(
        state_repo=_FakeStateRepo({"m1": _metric_events([10, 20, 30, 40])}),  # type: ignore[arg-type]
        window_s=60,
    )

    await service.refresh_now()
    snapshot = await service.get_metrics(metric_id="m1", include_events=False)
    aggregate = snapshot["metrics"][0]["aggregate"]

    assert aggregate["latency_avg_ms"] == 25.0
    assert aggregate["latency_median_ms"] == 25.0
    assert aggregate["latency_p95_ms"] == 40.0
    assert aggregate["latency_p99_ms"] == 40.0


@pytest.mark.asyncio
async def test_metrics_service_empty_window_has_null_latency_quantiles_spec() -> None:
    service = MetricsService(
        state_repo=_FakeStateRepo({}),  # type: ignore[arg-type]
        window_s=60,
    )

    snapshot = await service.get_metrics(metric_id="m-missing", include_events=False)
    aggregate = snapshot["metrics"][0]["aggregate"]

    assert aggregate["requests"] == 0
    assert aggregate["errors"] == 0
    assert aggregate["latency_avg_ms"] is None
    assert aggregate["latency_median_ms"] is None
    assert aggregate["latency_p95_ms"] is None
    assert aggregate["latency_p99_ms"] is None
