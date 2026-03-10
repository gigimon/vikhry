# vikhry

`vikhry` is an async distributed load-testing framework built for high concurrency, horizontal scaling, and workloads that need globally unique resources.

It combines:
- a Python runtime for writing virtual-user scenarios;
- an orchestrator that manages test lifecycle and aggregates metrics;
- worker processes that execute VUs;
- Redis as the shared coordination layer;
- a built-in web UI served by the orchestrator.

## Architecture

At a high level, `vikhry` has four runtime parts:

1. `orchestrator`
   Handles the test state machine, exposes HTTP/WebSocket APIs, serves the UI, and coordinates workers.
2. `worker`
   Runs VU tasks, processes orchestrator commands, publishes metrics, and manages acquired resources.
3. `redis`
   Stores shared state, worker presence, user assignments, resources, and metric streams.
4. `ui`
   A React frontend bundled into the Python package and served by the orchestrator.

Lifecycle flow:

`IDLE -> PREPARING -> RUNNING -> STOPPING -> IDLE`

## Install and run

Install from PyPI:

```bash
pip install vikhry
```

Start local infrastructure:

```bash
vikhry infra up --worker-count 3 --scenario my_scenario:DemoVU
```

This command:
- checks that Docker is available;
- starts Redis in a Docker container;
- starts the orchestrator;
- starts the requested number of workers.

Open:
- UI: `http://127.0.0.1:8080/`
- API: `http://127.0.0.1:8080`

Stop everything:

```bash
vikhry infra down
```

## Example test file

Create `my_scenario.py`:

```python
from __future__ import annotations

from typing import Any

from vikhry import ReqwestClient, VU, between, resource, step


@resource(name="users")
async def create_user(resource_id: int | str, _ctx: object) -> dict[str, Any]:
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

Run it:

```bash
vikhry infra up --worker-count 3 --scenario my_scenario:DemoVU
```

## Test authoring capabilities

`vikhry` scenarios are plain Python classes built on top of the VU DSL.

What you can define:
- `VU.on_init(...)`
  Accept runtime parameters for each VU instance.
- `VU.on_start()` / `VU.on_stop()`
  Allocate and release state or resources around the VU lifecycle.
- `@step(...)`
  Define executable load steps.
- `@resource(name="...")`
  Define global resource factories managed through Redis-backed pools.
- `ReqwestClient`
  Use an async HTTP client for relative or absolute requests.
- `emit_metric(...)` and `@metric(...)`
  Publish custom metrics in addition to automatic HTTP and step metrics.

Step controls:
- `weight`
  Weighted random scheduling between eligible steps.
- `requires`
  Declare prerequisites by step name.
- `every_s`
  Throttle step execution to a fixed or randomized interval.
- `timeout`
  Fail a step if it exceeds its maximum runtime.

Resource model:
- resource factories create globally tracked objects;
- workers acquire resources with `self.resources.acquire(name)`;
- workers release them with `self.resources.release(name, resource_id)`.

## Packaging and release

The Python package includes the built UI assets.

Build locally:

```bash
./scripts/build_frontend.sh
uv build
```

Release automation:
- `.github/workflows/release-artifacts.yml`
  Builds the frontend, creates `wheel` and `sdist`, and publishes the package to PyPI using `PYPI_TOKEN`.
- `.github/workflows/docker-image.yml`
  Builds and publishes the runtime Docker image to `ghcr.io/<owner>/<repo>` on every branch push.

The package version is taken from `project.version` in `pyproject.toml`.
