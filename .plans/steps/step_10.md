# Step 10: v1 Testing and Stabilization

## Goal

Add test coverage for the key orchestrator pieces:
- command contracts;
- allocator and lifecycle state machine;
- worker presence rules;
- integration with real Redis via Docker;
- failure and idempotency edge cases.

## Implementation

[x] Added unit tests:
  - `tests/unit/test_command_models.py`
  - `tests/unit/test_user_orchestration.py`
  - `tests/unit/test_worker_presence_service.py`
  - `tests/unit/test_lifecycle_service.py`
[x] Added integration tests against dockerized Redis:
  - `tests/integration/conftest.py`
  - `tests/integration/test_lifecycle_integration.py`
[x] Covered resilience and edge cases:
  - no alive workers during `start_test`
  - stale heartbeat
  - duplicate `add/remove` operations
  - rollback on start failure
[x] Updated end-user run documentation in `README.md`.
[ ] Structured logging and dedicated internal orchestrator runtime metrics
    (API latency, command rate, internal errors) remain a separate follow-up.

## Validation

`uv run pytest -q`
Result: `14 passed`
