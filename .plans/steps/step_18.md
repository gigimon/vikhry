# Step 18: Worker MVP Testing and Documentation

## Goal

Add test coverage for the worker MVP control plane and lock down:
- sequential command handling;
- strict epoch gating;
- idempotent user operations;
- the heartbeat contract in Redis.

## Implementation

[x] Added unit tests:
  - `tests/unit/test_worker_command_dispatcher.py`
  - `tests/unit/test_worker_heartbeat_service.py`
[x] Added integration tests against dockerized Redis:
  - `tests/integration/test_worker_services_integration.py`
[x] Covered scenarios:
  - `start_test -> add_user/remove_user -> stop_test` in the dispatcher
  - invalid JSON ignored in the command loop
  - stale commands ignored by `epoch`
  - duplicate `add_user/remove_user` operations stay idempotent
  - `healthy/unhealthy` heartbeat publication in `worker:{id}:status`
[x] Added an orchestrator + worker + CLI end-to-end smoke flow:
  - start orchestrator and worker via CLI
  - verify ready and alive worker detection
  - run `test start -> change-users -> stop`
  - verify Redis keyspace (`workers`, `worker:*:status`, `users`, `user:*`, `test:state`)
[x] Updated user documentation:
  - `README.md`
  - `docs/3_worker.md`
  - synchronized `docs/0_cli.md`, `docs/2_orchestrator.md`, `docs/contracts/v1.md`

## Validation

`uv run pytest -q`
Result: `23 passed`
