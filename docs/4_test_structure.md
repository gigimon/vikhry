# Scenario DSL

## Virtual User

A scenario is defined as a Python class derived from `VU`.

Example:

```python
from vikhry import ReqwestClient, VU, emit_metric, metric, resource, step


@resource(name="users")
async def create_user(resource_id, ctx):
    return {"resource_id": str(resource_id)}


class MyVU(VU):
    http = ReqwestClient(timeout=5)

    async def on_init(self, tenant: str, warmup: int = 1):
        self.tenant = tenant
        self.warmup = warmup

    async def on_start(self):
        self.user = await self.resources.acquire("users")

    @step(weight=3.0)
    async def get_catalog(self):
        await self.http.get("/catalog")

    @step(weight=1.0, requires=("get_catalog",), timeout=5.0)
    async def create_order(self):
        await emit_metric(name="order_validation", status=True, time=1.2)
        await self.http.post("/order")

    @metric(name="helper_auth", component="auth")
    async def helper_auth(self):
        await self.http.post("/auth")
```

## `on_init` parameters

The orchestrator extracts `VU.on_init` parameters from the scenario and exposes them through:
- `GET /scenario/on_init_params`

They can then be passed to:
- `POST /start_test` through `init_params`
- `vikhry test start --init-param key=value`
- `vikhry test start --init-params-json '{...}'`

## Starting a scenario

```bash
vikhry worker start --scenario my_scenario:MyVU --http-base-url https://api.example.com
```

## `@step(...)`

```python
@step(
    name=None,
    weight=1.0,
    every_s=None,
    requires=(),
    timeout=None,
    **strategy_kwargs,
)
```

Parameters:
- `name`
  Step name. Defaults to the function name.
- `weight`
  Weight used by the scheduler when selecting among eligible steps.
- `every_s`
  Minimum interval between executions.
- `requires`
  List of prerequisite step names that must already have succeeded.
- `timeout`
  Maximum allowed step runtime.
- `**strategy_kwargs`
  Extra metadata available to scheduling strategies.

Runtime behavior:
- eligible steps are chosen by weighted random selection;
- `requires` gates step eligibility;
- `every_s` limits execution frequency;
- each step execution produces metric events;
- HTTP requests also emit metrics automatically.

## Global resources

Resources are defined with `@resource`.

Example:

```python
@resource(name="users")
async def make_user(resource_id, ctx):
    response = await ctx.http.post("/register")
    return response.json()
```

Factory arguments:
1. `resource_id`
   Unique identifier for the resource instance
2. `ctx`
   Runtime context with environment-specific helpers

Workers consume resources through:
- `self.resources.acquire(name)`
- `self.resources.release(name, resource_id)`
