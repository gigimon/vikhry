# Step 3: Worker Presence Monitoring

## Goal

Implement alive-worker detection for orchestrator v1:
- a worker is alive only when `status=healthy`;
- heartbeat must not be stale;
- worker ordering must be deterministic;
- no-alive-worker situations must be handled explicitly.

## Chosen Alive Rule (Option A)

A worker is considered alive only if both conditions hold:
1. `worker:{worker_id}:status.status == healthy`
2. `now - last_heartbeat <= heartbeat_timeout_s`

## Implementation

[x] Added `WorkerPresenceService`:
  - `list_alive_workers()`
  - `refresh_cache()`
  - `cached_alive_workers()`
  - `require_alive_workers()`
[x] Added the domain error `NoAliveWorkersError` for operations that require alive workers.
[x] Connected periodic monitoring:
  - `WorkerMonitor` runs `on_tick=worker_presence.refresh_cache`
  - `on_tick` errors are logged and do not crash the loop.
[x] Enforced stable worker ordering through sorting in the Redis repository.
[x] Extended `/ready` with:
  - `alive_workers`
  - `workers`

## Notes

1. This step provided the foundation for lifecycle operations in Steps 4 and 5.
2. `require_alive_workers()` was prepared specifically for `start_test` and `change_users`.
