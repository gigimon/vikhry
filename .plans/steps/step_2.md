# Step 2: Contracts and Redis Layer

## Goal

Complete the orchestrator v1 contract layer:
- strict command and status models;
- a full Redis repository for the v1 keyspace;
- atomic lifecycle operations;
- command serialization and deserialization via `orjson`.

## Chosen Approach

Option `B` was chosen: use `Pydantic` for payload validation and typed models.

Reasons:
1. Strict validation of incoming command data.
2. Explicit contract errors during parsing.
3. Centralized schema ownership in a single model layer.

## Implementation

[x] Added the `pydantic` dependency.
[x] Implemented models:
  - `CommandType`, `CommandEnvelope`
  - `StartTestPayload`, `StopTestPayload`, `AddUserPayload`, `RemoveUserPayload`
  - `WorkerHealthStatus`, `WorkerStatus`
  - `UserRuntimeStatus`, `UserAssignment`
[x] Implemented command serialization:
  - `CommandEnvelope.to_json_bytes()`
  - `CommandEnvelope.from_json_bytes()`
[x] Expanded `TestStateRepository` to cover the v1 keyspace:
  - `test:*`
  - `workers`, `worker:*:status`, `worker:*:users`, `worker:*:commands`
  - `users`, `user:*`
  - `resources`, `resource:{name}:{id}`
  - `metrics`, `metric:{metric_id}`
[x] Added atomic operations:
  - compare-and-set for `test:state` through Lua;
  - atomic `IDLE -> PREPARING` with `epoch++` through Lua.

## Notes

1. The repository now covers the main v1 storage and pub/sub operations.
2. Business rules for the state machine stayed in the lifecycle service and were not pushed into the Redis layer.
