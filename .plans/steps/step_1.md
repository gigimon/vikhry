# Step 1: Orchestrator Process Skeleton

## Goal

Build the minimum orchestrator skeleton so later steps can add business logic without rebuilding the bootstrap layer.

## Decisions

1. Use the following package structure:
   - `vikhry/orchestrator/app.py`
   - `vikhry/orchestrator/api/`
   - `vikhry/orchestrator/services/`
   - `vikhry/orchestrator/redis_repo/`
   - `vikhry/orchestrator/models/`
2. Initialize the event loop with `uvloop.install()` before starting Robyn.
3. Initialize Redis keys such as `test:state` and `test:epoch` in `startup_handler`.
4. Perform graceful shutdown in `shutdown_handler`:
   - stop background tasks;
   - close the Redis client.
5. Add technical endpoints to validate the skeleton:
   - `GET /health`
   - `GET /ready`

## Implementation

[x] Created the `vikhry` package and the orchestrator subpackage.
[x] Added models (`OrchestratorSettings`, `TestState`).
[x] Added the Redis repository `TestStateRepository`.
[x] Added `WorkerMonitor` as a placeholder background loop.
[x] Built orchestrator bootstrap (`build_app`, `run_orchestrator`) on top of `Robyn + redis.asyncio + uvloop`.
[x] Added base API routes (`/health`, `/ready`).
[x] Added the CLI entrypoint `vikhry orchestrator start`.

## Notes

1. `orchestrator stop` remained a placeholder until a lifecycle manager was introduced.
2. Detailed alive-worker detection was intentionally deferred to Step 3.
