# Worker

## Current scope

The worker implements both control-plane handling and VU runtime execution:
- registration in Redis;
- heartbeat updates;
- subscription to personal command channels;
- sequential command processing;
- local user-task management;
- metric publishing;
- CLI start and stop behavior.

## Scenario loading

Workers load a VU class from an import path in the form:

`module.path:ClassName`

Relevant flags:
- `--scenario`
- `--http-base-url`
- `--vu-idle-sleep-s`
- `--vu-startup-jitter-ms`

## Stack

- `asyncio + uvloop`
- `redis.asyncio`
- `orjson`
- `Typer`

## Health payload

Workers publish `worker:{worker_id}:status` with:
- `status`
- `last_heartbeat`
- `cpu_percent`
- `rss_bytes`
- `total_ram_bytes`

On graceful shutdown, the worker performs a best-effort update to `status=unhealthy` before unregistering.

## Worker identity

- Default worker IDs are generated as `uuid4().hex[:8]`
- You may override the ID with `--worker-id`
- The same ID is reused consistently in all Redis keys for that process

## Command handling rules

1. Commands are processed strictly one at a time.
2. Invalid JSON and unknown command types are ignored with logging.
3. `ack` and `nack` are not used.
4. `start_test` with a newer epoch switches the local epoch.
5. `add_user`, `remove_user`, and `stop_test` require `command.epoch == current_epoch`.
6. Command handlers must remain idempotent.

## Local lifecycle

Initial state:
- `phase=IDLE`
- `current_epoch=0`
- `assigned_users=empty`

Transitions:
- `start_test`
  Switches the worker to `RUNNING`
- `add_user`
  Creates a VU task and tracks the assignment
- `remove_user`
  Stops the VU task and removes the assignment
- `stop_test`
  Stops all user tasks, clears local state, and returns to `IDLE`

Users are added to `worker:{worker_id}:active_users` only after successful `on_init` and `on_start`.

## Logging

Workers log:
- startup;
- Redis connectivity;
- command loop startup;
- command receipt with `command_id`, `type`, and `epoch`;
- shutdown.

## CLI examples

```bash
vikhry worker start --redis-url redis://127.0.0.1:6379/0
vikhry worker start --foreground --worker-id w1
vikhry worker start --scenario my_scenario:DemoVU --http-base-url https://api.example.com
vikhry worker stop --pid-file /path/to/worker.pid
```
