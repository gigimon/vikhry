# Step 11: Worker MVP Foundation (Control Plane)

## Goal

Launch the first working `worker` implementation for the v1 contract without executing DSL scenarios yet:
- register and heartbeat in Redis;
- process commands sequentially from a personal channel;
- use strict epoch gating with transitions only on `start_test`;
- support worker lifecycle control from CLI (`start/stop`, detached or foreground).

## Implementation

[x] Added the `vikhry/worker` package:
  - `vikhry/worker/app.py`
  - `vikhry/worker/models/*`
  - `vikhry/worker/redis_repo/*`
  - `vikhry/worker/services/*`
[x] Implemented worker bootstrap:
  - `uvloop` plus async runtime
  - Redis connection
  - graceful shutdown on `SIGINT` and `SIGTERM`
[x] Implemented registration and heartbeat:
  - `workers` registry
  - `worker:{id}:status` with `healthy/unhealthy` and `last_heartbeat`
  - unregister on shutdown
[x] Implemented the single-threaded command loop:
  - subscribe to `worker:{worker_id}:commands`
  - ignore invalid JSON and unknown types
  - handle `start_test`, `stop_test`, `add_user`, `remove_user`
[x] Implemented MVP lifecycle:
  - `start_test` moves worker to `RUNNING`
  - `add/remove_user` update the local user set idempotently
  - `stop_test` gracefully stops local tasks and clears state
[x] Added CLI integration:
  - `vikhry worker start`
  - `vikhry worker stop`
  - hidden `vikhry worker serve` for detached mode
  - auto-generated short `worker_id` values
[x] Updated orchestrator command ordering for epoch compatibility:
  - `start_test` is sent before `add_user`

## Validation

`uv run pytest -q`
Result: `14 passed`

`uv run python -m vikhry.cli --help`
Result: the CLI includes the new `worker` group
