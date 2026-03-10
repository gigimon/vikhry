# Orchestrator

## Technology stack

The orchestrator uses:
- `asyncio` with `uvloop`;
- `robyn` for HTTP and WebSocket APIs;
- `redis.asyncio` for shared coordination;
- `orjson` for command and payload serialization.

## Responsibilities

The orchestrator is responsible for:
- initializing runtime state in Redis;
- tracking alive workers from heartbeats;
- executing the test state machine;
- creating and counting resources;
- distributing users across workers;
- aggregating metrics for CLI and UI;
- serving the bundled web UI.

## v1 rules

1. Runtime configuration comes only from CLI flags.
2. Only one test can run at a time.
3. There is no orchestrator locking across multiple orchestrator instances.
4. Command acknowledgements are not implemented.
5. Commands are sent only to per-worker channels.

## State machine

The orchestrator manages:

`IDLE -> PREPARING -> RUNNING -> STOPPING -> IDLE`

Allowed transitions:
- `start_test` only from `IDLE`
- `change_users` only from `RUNNING`
- `stop_test` from `PREPARING` or `RUNNING`

## Worker command format

```json
{
  "type": "add_user",
  "command_id": "uuid",
  "epoch": 1,
  "sent_at": 1761571200,
  "payload": {
    "user_id": 10
  }
}
```

Supported command types:
- `start_test`
- `stop_test`
- `add_user`
- `remove_user`

## Runtime behavior

### `start_test`

1. Validate that the current state is `IDLE`.
2. Set `test:state=PREPARING`.
3. Increment `test:epoch`.
4. Prepare or extend resources.
5. Send `start_test` to each alive worker.
6. Allocate users with round-robin.
7. Send `add_user` commands.
8. Set `test:state=RUNNING`.

### `change_users`

1. Compute the delta against the current user count.
2. Send `add_user` when scaling up.
3. Send `remove_user` when scaling down.

### `stop_test`

1. Set `test:state=STOPPING`.
2. Send `stop_test` to alive workers.
3. Clear user-related Redis keys.
4. Keep resources intact.
5. Set `test:state=IDLE`.

## API surface

v1 endpoints:
- `GET /health`
- `GET /ready`
- `POST /start_test`
- `POST /change_users`
- `POST /stop_test`
- `POST /create_resource`
- `POST /ensure_resource`
- `GET /metrics`
- `GET /workers`
- `GET /resources`
- `GET /scenario/on_init_params`
- `GET /metrics/history`
- `GET /ws/metrics`

`/start_test` accepts:
- `target_users`
- `init_params` as an optional object for `VU.on_init`
