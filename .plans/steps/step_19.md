# Step 19: API Contracts for UI

## Goal

Prepare backend contracts for the `Workers` and `Resources` UI tabs:
- add dedicated read endpoints `/workers` and `/resources`;
- stabilize JSON responses for the frontend;
- cover the changes with unit and integration tests.

## Implementation

[x] Added `GET /workers` in the orchestrator API:
  - returns `generated_at`, `count`, and `workers[]`
  - each worker includes `worker_id`, `status`, `last_heartbeat`, `heartbeat_age_s`, `users_count`
  - supports `null` status and heartbeat fields for workers without published health status
[x] Added `GET /resources` in the orchestrator API:
  - returns `generated_at`, `count`, and `resources[]`
  - each row includes `resource_name` and `count` from the `resources` Redis hash
[x] Updated route wiring:
  - `register_routes(...)` now receives `state_repo` and uses it for snapshot endpoints
[x] Updated contract documentation:
  - added `Orchestrator HTTP API (v1)` section to `docs/contracts/v1.md`
  - added examples and response descriptions for `/workers` and `/resources`
[x] Added tests:
  - unit: `tests/unit/test_orchestrator_api_routes.py`
  - integration: `tests/integration/test_orchestrator_api_endpoints.py`

## Validation

- `uv run pytest tests/unit/test_orchestrator_api_routes.py -q` -> `2 passed`
- `uv run pytest tests/integration/test_orchestrator_api_endpoints.py -q` -> `1 passed`
- `uv run ruff check vikhry/orchestrator/api/routes.py vikhry/orchestrator/app.py tests/unit/test_orchestrator_api_routes.py tests/integration/test_orchestrator_api_endpoints.py` -> `All checks passed!`
