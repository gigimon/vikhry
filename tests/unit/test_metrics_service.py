from __future__ import annotations

from typing import Any

import pytest

from vikhry.orchestrator.services.metrics_service import MetricsService


class _FakeStateRepo:
    def __init__(self, events_by_metric: dict[str, list[dict[str, Any]]]) -> None:
        self._events_by_metric = {
            metric_id: list(events) for metric_id, events in events_by_metric.items()
        }
        self.metrics_cleared = False

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

    async def clear_metrics_data(self) -> int:
        keys = len(self._events_by_metric) + 1
        self.metrics_cleared = True
        self._events_by_metric.clear()
        return keys


class _FailingListMetricsRepo:
    async def list_metrics(self) -> list[str]:
        raise RuntimeError("boom")


def _metric_events(
    latencies: list[float],
    *,
    statuses: list[bool] | None = None,
    result_codes: list[str] | None = None,
    result_categories: list[str] | None = None,
    fatal_indices: set[int] | None = None,
    start_ts_ms: int = 1_700_000_000_000,
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    fatal_set = fatal_indices or set()
    for index, latency in enumerate(latencies):
        ts_ms = start_ts_ms + index
        status = statuses[index] if statuses is not None else True
        result_code = result_codes[index] if result_codes is not None else "HTTP_200"
        result_category = result_categories[index] if result_categories is not None else "ok"
        events.append(
            {
                "event_id": f"{ts_ms}-{index}",
                "data": {
                    "ts_ms": ts_ms,
                    "status": status,
                    "time": latency,
                    "result_code": result_code,
                    "result_category": result_category,
                    "fatal": index in fatal_set,
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
    aggregate_total = snapshot["metrics"][0]["aggregate_total"]

    assert aggregate["latency_avg_ms"] == 30.0
    assert aggregate["latency_median_ms"] == 30.0
    assert aggregate["latency_p95_ms"] == 50.0
    assert aggregate["latency_p99_ms"] == 50.0
    assert aggregate["result_code_counts"] == {"HTTP_200": 5}
    assert aggregate["result_category_counts"] == {"ok": 5}
    assert aggregate["fatal_count"] == 0
    assert aggregate["top_result_codes"] == [{"result_code": "HTTP_200", "count": 5}]
    assert aggregate_total["requests"] == 5
    assert aggregate_total["errors"] == 0
    assert aggregate_total["latency_avg_ms"] == 30.0
    assert aggregate_total["latency_p95_ms"] == 50.0
    assert aggregate_total["window_s"] >= 1
    assert aggregate_total["result_code_counts"] == {"HTTP_200": 5}
    assert aggregate_total["result_category_counts"] == {"ok": 5}
    assert aggregate_total["fatal_count"] == 0


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
    assert aggregate["result_code_counts"] == {"HTTP_200": 4}
    assert aggregate["result_category_counts"] == {"ok": 4}
    assert aggregate["fatal_count"] == 0


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
    assert aggregate["result_code_counts"] == {}
    assert aggregate["result_category_counts"] == {}
    assert aggregate["fatal_count"] == 0


@pytest.mark.asyncio
async def test_metrics_service_get_metrics_degrades_when_metrics_index_unavailable_spec() -> None:
    service = MetricsService(
        state_repo=_FailingListMetricsRepo(),  # type: ignore[arg-type]
        window_s=60,
    )

    snapshot = await service.get_metrics(include_events=False)

    assert snapshot["metrics"] == []
    assert snapshot["include_events"] is False


@pytest.mark.asyncio
async def test_metrics_service_reset_for_new_run_clears_redis_and_in_memory_state_spec() -> None:
    repo = _FakeStateRepo({"m1": _metric_events([10, 20, 30])})
    service = MetricsService(
        state_repo=repo,  # type: ignore[arg-type]
        window_s=60,
    )

    await service.refresh_now()
    before = await service.get_metrics(include_events=False)
    assert len(before["metrics"]) == 1

    await service.reset_for_new_run()
    after = await service.get_metrics(include_events=False)

    assert repo.metrics_cleared is True
    assert after["metrics"] == []


@pytest.mark.asyncio
async def test_metrics_service_aggregates_result_breakdown_with_top_k_spec() -> None:
    service = MetricsService(
        state_repo=_FakeStateRepo(
            {
                "m1": _metric_events(
                    [10, 11, 12, 13, 14, 15],
                    statuses=[True, True, False, False, False, False],
                    result_codes=[
                        "HTTP_200",
                        "HTTP_200",
                        "HTTP_500",
                        "HTTP_500",
                        "STEP_EXCEPTION",
                        "CUSTOM_X",
                    ],
                    result_categories=[
                        "ok",
                        "ok",
                        "protocol_error",
                        "protocol_error",
                        "exception",
                        "transport_error",
                    ],
                    fatal_indices={4},
                )
            }
        ),  # type: ignore[arg-type]
        window_s=60,
        max_result_codes=2,
    )

    await service.refresh_now()
    snapshot = await service.get_metrics(metric_id="m1", include_events=False)
    aggregate = snapshot["metrics"][0]["aggregate"]
    aggregate_total = snapshot["metrics"][0]["aggregate_total"]

    assert aggregate["requests"] == 6
    assert aggregate["errors"] == 4
    assert aggregate["fatal_count"] == 1
    assert aggregate["result_code_counts"] == {
        "HTTP_200": 2,
        "HTTP_500": 2,
        "OTHER": 2,
    }
    assert aggregate["top_result_codes"] == [
        {"result_code": "HTTP_200", "count": 2},
        {"result_code": "HTTP_500", "count": 2},
        {"result_code": "OTHER", "count": 2},
    ]
    assert aggregate["result_category_counts"] == {
        "ok": 2,
        "protocol_error": 2,
        "exception": 1,
        "transport_error": 1,
    }
    assert aggregate_total["result_code_counts"] == aggregate["result_code_counts"]
