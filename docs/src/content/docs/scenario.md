---
title: Scenario
description: Structure of a vikhry scenario file and the main DSL primitives.
sidebar:
  order: 3
---

## Example scenario

```python
from __future__ import annotations

from typing import Any

from vikhry import ReqwestClient, VU, between, resource, step


@resource(name="users")
async def create_user_resource(resource_id: int | str, _ctx: object) -> dict[str, Any]:
    rid = str(resource_id)
    return {
        "resource_id": rid,
        "username": f"user_{rid}",
        "password": "password",
    }


class DemoVU(VU):
    http = ReqwestClient(timeout=5.0)

    async def on_init(self, base_url: str) -> None:
        self.http = self.http(base_url=base_url)

    async def on_start(self) -> None:
        self.user = await self.resources.acquire("users")

    async def on_stop(self) -> None:
        await self.resources.release("users", str(self.user["resource_id"]))

    @step(name="login", weight=1.0, every_s=between(10.0, 15.0), timeout=5.0)
    async def login(self) -> None:
        response = await self.http.post(
            "/auth",
            json={
                "username": self.user["username"],
                "password": self.user["password"],
            },
        )
        if response.status >= 400:
            raise RuntimeError(f"login returned HTTP {response.status}")

    @step(name="catalog", weight=3.0, requires=("login",), every_s=between(0.2, 1.0))
    async def catalog(self) -> None:
        response = await self.http.get("/catalog")
        if response.status >= 400:
            raise RuntimeError(f"catalog returned HTTP {response.status}")
```

## What happens in this file

This file defines two things:

- a global resource factory named `users`
- a virtual user class named `DemoVU`

Each worker creates `DemoVU` instances for assigned users and runs their lifecycle and steps.

## `resource`

`@resource(name="users")` declares a resource factory. The factory is an async function that receives a `resource_id` and returns a JSON-like object describing that resource.

Resources are global for the whole test run:

- they are tracked through Redis
- workers acquire them with `self.resources.acquire(name)`
- workers release them with `self.resources.release(name, resource_id)`

Use resources when multiple workers need unique shared entities such as users, accounts, sessions, wallets, or API keys.

## `on_init`

`on_init(...)` runs before the active step loop starts. It is the place to accept runtime parameters and prepare per-user state such as an HTTP client configured with a base URL.

Parameters for `on_init(...)` come from the runtime when the test is started. The orchestrator receives them from the CLI or UI, passes them through Redis inside the `start_test` command payload, and each worker then calls `vu.on_init(**init_params)` for every created VU.

That means the names in `init_params` must match the argument names of `on_init(...)`.

Parameters for `on_init(...)` are passed from the CLI:

```bash
vikhry test start \
  --users 10 \
  --init-param base_url=http://localhost:8000
```

With this scenario:

```python
class DemoVU(VU):
    http = ReqwestClient(timeout=5.0)

    async def on_init(self, base_url: str) -> None:
        self.http = self.http(base_url=base_url)
```

the runtime does the equivalent of:

```python
await vu.on_init(base_url="http://localhost:8000")
```

Why this is useful:

- `http = ReqwestClient(timeout=5.0)` defines a reusable HTTP client template on the class
- `base_url` is not hardcoded in the scenario file
- `on_init(...)` turns that template into a per-VU client bound to the target environment

After that, steps can use relative paths:

```python
response = await self.http.get("/catalog")
```

and the client will resolve them against the runtime-provided `base_url`.

This makes the same scenario reusable across environments such as:

- local development
- staging
- production-like test environments

without changing the scenario code itself.

## `self.http`

`self.http` is the VU HTTP client used inside steps.

In a typical scenario:

- the class defines an HTTP template such as `http = ReqwestClient(timeout=5.0)`
- `on_init(...)` materializes it into a per-VU client, often with a `base_url`
- steps use `self.http.get(...)`, `self.http.post(...)`, and other HTTP methods

The default HTTP stack is instrumented, so HTTP calls also produce runtime metrics automatically.

`self.http` is not limited to plain HTTP requests. It can also be backed by `JsonRPCClient`, in which case steps use `self.http.call(...)` instead of `get(...)` or `post(...)`.

## Lifecycle hooks around the run

The current runtime lifecycle hooks are:

- `on_init(...)`
- `on_start()`
- `on_stop()`

`on_start()` is typically used to acquire resources before the step loop begins.  
`on_stop()` is typically used to release resources and clean up.

There is no separate `on_setup()` hook in the current DSL.

## `step`

`@step(...)` marks an async method as an executable load step. During the run, the worker selects eligible steps and executes them for each VU.

By default, `vikhry` uses a sequential weighted strategy:

- only steps whose prerequisites are satisfied can run
- if several steps are ready, selection is weighted by `weight`
- after a step runs, `every_s` controls when it becomes eligible again

## Step fields

### `name`

Human-readable step name. If omitted, the Python method name is used.

### `weight`

Relative probability of selecting the step when multiple steps are ready. The value must be greater than `0`.

### `requires`

Tuple of prerequisite step names. A step becomes eligible only after all required steps have completed at least once.

### `every_s`

Throttle interval between executions of the same step.

It can be:

- a fixed number like `every_s=1.5`
- a callback such as `between(0.2, 1.0)` for randomized delays

### `timeout`

Maximum allowed execution time for the step. If the timeout is exceeded, the step fails.
