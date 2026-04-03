# Step 9: CLI Integration

## Goal

Upgrade the CLI to the v1 contract:
- use `Typer` as the CLI framework;
- add commands to start and stop the orchestrator;
- add test-control commands via orchestrator HTTP API;
- pass runtime parameters only through CLI flags;
- provide operationally useful errors.

## Implementation

[x] Migrated the CLI to `Typer`:
  - `orchestrator` group
  - `test` group
[x] Added orchestrator commands:
  - `vikhry orchestrator start`
  - `vikhry orchestrator stop`
[x] Added `--scenario` to `orchestrator start` and pass it into orchestrator runtime.
[x] Added PID-based process control to `orchestrator stop`:
  - `--pid-file`
  - graceful stop escalation `SIGINT -> SIGTERM`
  - optional `--force` (`SIGKILL`) and `--timeout-s`
[x] Added detached mode to `orchestrator start` by default:
  - background launch with terminal control returned immediately;
  - `--foreground` for blocking mode;
  - `--log-file` and `--startup-timeout-s` for diagnostics
[x] Moved default pid and log paths into the platform runtime directory instead of the repository root.
[x] Added test commands over HTTP:
  - `vikhry test start --users ...`
  - `vikhry test change-users --users ...`
  - `vikhry test stop`
[x] Implemented the HTTP client via `pyreqwest` (`SyncClientBuilder`).
[x] Added validation and user-facing errors for:
  - orchestrator URL
  - HTTP and network failures
  - invalid pid and stale pid file cases
[x] Ensured all orchestrator runtime parameters are passed through CLI flags.

## Notes

1. `orchestrator stop` does not depend on an API shutdown endpoint; it uses the pid file directly.
2. Test commands support `--orchestrator-url` and `--timeout-s` for operational flexibility.
3. The CLI prints orchestrator JSON responses in pretty-printed form for diagnostics.
