# Step 20: Metrics Expansion (Exact Percentiles)

## Goal

Expand live metric aggregates in orchestrator for the UI:
- add exact `median`, `p95`, and `p99` latency values within the `window_s` window;
- preserve compatibility with the existing contract (`requests/errors/rps/latency_avg_ms`);
- cover calculations with edge-case tests.

## Implementation

[x] Updated `MetricsService` (`vikhry/orchestrator/services/metrics_service.py`):
  - `_MetricBucket` stores all `latencies_ms` samples within each second
  - window aggregation uses the exact sample set
  - added `latency_median_ms`, `latency_p95_ms`, `latency_p99_ms`
[x] Added helpers:
  - `_sorted_median(...)`
  - `_sorted_percentile_nearest_rank(..., percentile=95|99)`
[x] Updated snapshot contracts (`/metrics`, `metrics_snapshot`, `metrics_tick`):
  - new latency quantiles are returned together with the old fields
  - all `latency_*` fields return `null` when no latency samples exist
[x] Preserved backward compatibility for all previous aggregate fields.
[x] Added unit tests in `tests/unit/test_metrics_service.py`:
  - odd sample size
  - even sample size
  - empty window
[x] Updated `docs/contracts/v1.md` with the new aggregate fields.

## Validation

- `uv run pytest tests/unit/test_metrics_service.py -q` -> `3 passed`
- `uv run pytest tests/integration/test_orchestrator_api_endpoints.py -q` -> `1 passed`
- `uv run ruff check vikhry/orchestrator/services/metrics_service.py tests/unit/test_metrics_service.py` -> `All checks passed!`
