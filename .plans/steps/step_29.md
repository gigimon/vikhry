# Step 29: Runtime Emitters and Backend Error Aggregation

## Goal

Connect the unified outcome contract to runtime event sources and aggregate it in orchestrator `/metrics`.

## Implementation

[x] Updated lifecycle runtime:
  - emit failure metrics from `on_init` and `on_start` with `source=lifecycle`, proper `stage`, and `fatal=true`
  - do not start the step loop after such failures
[x] Updated step runtime:
  - emit success outcomes with `result_code=STEP_OK`, `result_category=ok`
  - emit failure outcomes with `result_code=STEP_EXCEPTION`, `result_category=exception`, `error_type`, and `error_message`
[x] Updated HTTP runtime:
  - responses use `result_code=HTTP_<status>`
  - exceptions use `result_code=HTTP_EXCEPTION` and normalized categories
[x] Expanded orchestrator `MetricsService`:
  - `result_code_counts`
  - `result_category_counts`
  - `fatal_count`
  - top-K result codes plus `OTHER`
[x] Updated `/metrics` contract and `docs/contracts/v1.md`.
[x] Added unit tests for aggregation and lifecycle/step/HTTP failure paths.

## Progress

- [x] Runtime emitters updated
- [x] `/metrics` aggregation expanded
- [x] Backend tests passing
