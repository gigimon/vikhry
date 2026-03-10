# CLI

## Goals

The CLI is the single entrypoint for:

1. starting and stopping runtime components;
2. bootstrapping local infrastructure;
3. controlling test lifecycle through the orchestrator API.

Main command groups:
- `vikhry orchestrator`
- `vikhry worker`
- `vikhry test`
- `vikhry infra`

## Common commands

```bash
vikhry orchestrator start --host 127.0.0.1 --port 8080 --redis-url redis://127.0.0.1:6379/0
vikhry worker start --scenario my_scenario:DemoVU --http-base-url https://api.example.com
vikhry test start --users 100 --orchestrator-url http://127.0.0.1:8080
vikhry test change-users --users 150 --orchestrator-url http://127.0.0.1:8080
vikhry test stop --orchestrator-url http://127.0.0.1:8080
```

## Local infrastructure bootstrap

```bash
vikhry infra up --worker-count 3 --scenario my_scenario:DemoVU
vikhry infra down
```

`infra up`:
- checks Docker CLI and daemon availability;
- starts Redis in the `vikhry-redis-infra` container;
- starts the orchestrator in detached mode;
- starts the requested number of workers in detached mode;
- performs best-effort cleanup if startup fails halfway through.

## Runtime model

By default:
- `orchestrator start` runs detached;
- `worker start` runs detached;
- `infra up` stores `pid` and `log` files under the runtime directory.

Foreground mode is available with `--foreground`.

## Process control

PID-based stop commands:
- `vikhry orchestrator stop --pid-file ... [--timeout-s ...] [--force]`
- `vikhry worker stop --pid-file ... [--timeout-s ...] [--force]`

Default runtime directories:
- macOS: `~/Library/Caches/vikhry/`
- Linux: `$XDG_RUNTIME_DIR/vikhry/` or `/run/user/<uid>/vikhry/`, fallback `/tmp/vikhry/`

`infra` uses the subdirectory `.../vikhry/infra/`.

## Scenario-related options

Worker options:
- `--scenario module.path:ClassName`
- `--http-base-url`
- `--vu-idle-sleep-s`
- `--vu-startup-jitter-ms`

Orchestrator options:
- `--scenario module.path:ClassName`

The orchestrator uses the scenario import path to discover:
- declared resources;
- the `VU.on_init` parameter schema.

## Test control

The `vikhry test` group talks to the orchestrator over HTTP using `pyreqwest`.

Supported actions:
- `start`
- `change-users`
- `stop`

`start` supports:
- `--users`
- `--init-param key=value`
- `--init-params-json '{...}'`
