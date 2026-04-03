# Step 39: Worker-side probe runtime

## Goal

Run probe functions on workers independently from VU execution and only on probe-enabled workers.

## Scope

- Add a dedicated probe runtime/service on worker side, separate from `WorkerVURuntime`.
- Start probe runtime only when worker is launched with `--run-probes`.
- Run probes only while the active test lifecycle is `RUNNING`.
- Schedule each probe independently by its own `every_s`.
- Apply `timeout` per probe execution.
- Treat probe failure only as probe failure; it must not affect VU runtime.
- Support graceful stop when test stops or worker shuts down.

## Implementation

[x] Added a dedicated worker probe runtime/service.
[x] Loaded probe targets from the scenario module.
[x] Wired worker startup to enable probe runtime only with `--run-probes`.
[x] Scheduled each probe independently using its own `every_s`.
[x] Applied per-probe execution timeout.
[x] Kept probe failures isolated from VU runtime.
[x] Added graceful stop for worker shutdown and test stop.

## Verification

[x] Unit coverage added for scheduling, timeout handling, failure isolation, and stop semantics.
