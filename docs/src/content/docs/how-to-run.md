---
title: How to run
description: Install vikhry from PyPI and run it through the CLI.
sidebar:
  order: 2
---

## Installation

Install `vikhry` from PyPI:

```bash
pip install vikhry
```

At the moment, PyPI is the only supported installation method.

## Run the full local stack with `infra`

For local work, the fastest way to start everything is:

```bash
vikhry infra up --worker-count 3 --scenario my_scenario:DemoVU
```

This command:

- checks that Docker is available
- starts Redis in a local Docker container
- starts the orchestrator
- starts the requested number of workers

After startup:

- UI: `http://127.0.0.1:8080/`
- API: `http://127.0.0.1:8080`

Stop the full stack with:

```bash
vikhry infra down
```

## Web UI

The built-in UI is served by the orchestrator.

By default, open:

```text
http://127.0.0.1:8080/
```

If you start the orchestrator with another `--port`, the UI moves to that port as well.

## Run components separately

If you do not want to use `infra`, you can run Redis, the orchestrator, and workers as separate processes.

### 1. Start Redis

`vikhry` expects a Redis instance. By default, the CLI uses:

```text
redis://127.0.0.1:6379/0
```

How Redis is started is up to you.

### 2. Start the orchestrator

```bash
vikhry orchestrator start --scenario my_scenario:DemoVU
```

By default, this starts the API and UI on port `8080`, so the interface is available at `http://127.0.0.1:8080/`.

Useful options:

- `--host` and `--port` to change bind address
- `--redis-url` to point to another Redis instance
- `--detach/--foreground` to choose background or foreground mode

Stop it with:

```bash
vikhry orchestrator stop
```

### 3. Start one or more workers

```bash
vikhry worker start \
  --worker-id worker-1 \
  --scenario my_scenario:DemoVU
```

Start more workers with different `--worker-id` values.

Useful options:

- `--redis-url` to connect to the same Redis as the orchestrator
- `--http-base-url` to set a default base URL for relative HTTP calls
- `--detach/--foreground` to choose background or foreground mode

Stop a worker with:

```bash
vikhry worker stop
```

### 4. Start and control a test

Start a test with a target number of users:

```bash
vikhry test start --users 10
```

If your scenario `on_init(...)` requires parameters, pass them through the CLI:

```bash
vikhry test start \
  --users 10 \
  --init-param base_url=http://localhost:8000
```

Change the target users during a run:

```bash
vikhry test change-users --users 25
```

Stop the test:

```bash
vikhry test stop
```
