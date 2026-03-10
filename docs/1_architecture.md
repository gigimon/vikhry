# Architecture

## Core components

`vikhry` consists of four major pieces:

1. Orchestrator
   The central control-plane service. It manages test lifecycle, talks to Redis, exposes HTTP/WebSocket APIs, and serves the UI.
2. Worker
   A separate process that executes VUs, handles orchestrator commands, and publishes metrics.
3. Redis
   The shared coordination layer for state, commands, resources, and metric streams.
4. UI
   A React frontend that is bundled into the Python package and served by the orchestrator.

## v1 constraints

1. There is only one active test at a time.
2. There is no `run_id`.
3. No distributed orchestrator lock is implemented.
4. Worker commands are sent through Redis Pub/Sub.
5. Commands are delivered per worker, not through a broadcast channel.
6. `ack` and `nack` are not part of the v1 protocol.
7. User scaling is done only through `add_user` and `remove_user`.
8. User distribution uses round-robin across alive workers.

## Redis keyspace overview

### Test state
- `test:state`
  Current lifecycle state: `IDLE | PREPARING | RUNNING | STOPPING`
- `test:epoch`
  Incremented on each `start_test`

### Users
- `users`
  Set of active user IDs
- `user:{user_id}`
  Per-user status, assigned worker, and timestamps

### Resources
- `resources`
  Resource counters by name
- `resource:{resource_name}:{id}`
  Serialized resource payload

### Workers
- `workers`
  Registered worker IDs
- `worker:{worker_id}:commands`
  Pub/Sub command channel for a specific worker
- `worker:{worker_id}:users`
  Assigned users
- `worker:{worker_id}:active_users`
  Users that successfully passed `on_init` and `on_start`
- `worker:{worker_id}:status`
  Worker heartbeat and health payload

### Metrics
- `metrics`
  Known metric IDs
- `metric:{metric_id}`
  Redis stream of raw metric events

## Lifecycle flow

### Component startup

1. The orchestrator connects to Redis and initializes test state keys.
2. Each worker registers itself in `workers`.
3. Each worker subscribes to its personal command channel.
4. Workers update their heartbeat in `worker:{worker_id}:status`.
5. The orchestrator periodically refreshes the alive-worker cache from heartbeats.

### Test start

1. The orchestrator validates that the current state is `IDLE`.
2. It switches the state to `PREPARING`.
3. It increments `test:epoch`.
4. It prepares resources.
5. It sends `start_test` to alive workers.
6. It distributes users with round-robin and sends `add_user`.
7. It switches the state to `RUNNING`.

### User count change

1. The operation is allowed only in `RUNNING`.
2. Scale up sends `add_user`.
3. Scale down sends `remove_user`.

### Test stop

1. The orchestrator switches the state to `STOPPING`.
2. It sends `stop_test` to alive workers.
3. It clears user-related keys.
4. It leaves resources intact.
5. It switches the state back to `IDLE`.
