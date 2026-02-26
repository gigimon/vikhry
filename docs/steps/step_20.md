# Step 20: Расширение метрик (exact percentiles)

## Цель

Расширить агрегаты live-метрик в orchestrator для UI:
- добавить exact `median`, `p95`, `p99` по latency в рамках окна `window_s`;
- сохранить совместимость текущего контракта (`requests/errors/rps/latency_avg_ms`);
- покрыть вычисления тестами на edge-cases.

## Реализация

[x] Обновлен `MetricsService` (`vikhry/orchestrator/services/metrics_service.py`):
  - `_MetricBucket` хранит `latencies_ms` (все sample latency внутри секунды);
  - в агрегации окна используется exact выборка всех latency sample;
  - добавлены поля `latency_median_ms`, `latency_p95_ms`, `latency_p99_ms`.
[x] Добавлены вспомогательные функции:
  - `_sorted_median(...)` (median с поддержкой четного/нечетного числа sample);
  - `_sorted_percentile_nearest_rank(..., percentile=95|99)` для exact percentile по nearest-rank.
[x] Обновлен snapshot contract (`/metrics`, `metrics_snapshot`, `metrics_tick`):
  - новые latency quantile поля возвращаются вместе с существующими;
  - при отсутствии latency sample все `latency_*` поля возвращают `null`.
[x] Сохранена backward compatibility:
  - все старые поля aggregate остаются неизменными.
[x] Добавлены unit тесты `tests/unit/test_metrics_service.py`:
  - odd sample size;
  - even sample size;
  - empty window (null quantiles).
[x] Обновлена контрактная документация `docs/contracts/v1.md`:
  - секция `GET /metrics` дополнена новыми полями aggregate.

## Прогон проверок

- `uv run pytest tests/unit/test_metrics_service.py -q` -> `3 passed`
- `uv run pytest tests/integration/test_orchestrator_api_endpoints.py -q` -> `1 passed`
- `uv run ruff check vikhry/orchestrator/services/metrics_service.py tests/unit/test_metrics_service.py` -> `All checks passed!`
