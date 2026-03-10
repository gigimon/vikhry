---
title: Customization
description: How to customize the VU HTTP client and step scheduling strategy.
sidebar:
  order: 4
---

## What can be customized

Two important runtime extension points on a `VU` are:

- `http`: the HTTP client used by steps
- `step_strategy`: the scheduler that decides which ready steps run next

In practice:

- the HTTP client defines how a VU sends requests and how those requests are configured
- the step strategy defines how the runtime selects ready steps during the execution loop

These two attributes are the main customization points for request behavior and step scheduling.

## Default `self.http`

Every `VU` has an `http` attribute. In the base runtime, the default is:

```python
http = ReqwestClient()
```

That means:

- the default HTTP implementation is based on `ReqwestClient`
- the runtime creates a separate client instance per VU
- the client is wrapped with instrumentation, so HTTP metrics are emitted automatically

In practice, steps call methods like:

```python
await self.http.get("/catalog")
await self.http.post("/auth", json=payload)
```

## How to override `self.http`

The most common override is to replace the class attribute with another `ReqwestClient` configuration:

```python
from vikhry import ReqwestClient, VU


class DemoVU(VU):
    http = ReqwestClient(timeout=5.0)
```

Then, in `on_init(...)`, you can bind a `base_url` for that VU:

```python
async def on_init(self, base_url: str) -> None:
    self.http = self.http(base_url=base_url)
```

You can also provide your own HTTP client or factory instead of `ReqwestClient`. The runtime accepts:

- an object with async `request(...)`
- an object with `create(...)` returning a client with async `request(...)`
- a callable returning a client with async `request(...)`

So custom transports are possible as long as they match the expected interface.

## What `ReqwestClient` is

`ReqwestClient` is a lazy template, not the final connected client itself.

It is used to define defaults such as:

- `base_url`
- `timeout`

When the VU starts, the runtime resolves that template into an instrumented per-user HTTP client.

## Default `step_strategy`

Every `VU` also has a `step_strategy` attribute. The default is:

```python
step_strategy = SequentialWeightedStrategy()
```

This is the default scheduler for the VU step loop.

## How `SequentialWeightedStrategy` works

The runtime first determines which steps are ready:

- all step names listed in `requires` must already be completed
- if `every_s` is set, the step must wait until its next allowed execution time

After that:

- if no steps are ready, the VU sleeps briefly
- if one step is ready, that step runs
- if multiple steps are ready, one step is chosen using `weight`

So the default behavior is sequential execution with weighted random choice among ready steps.

## How to override `step_strategy`

You can replace the default strategy on the VU class:

```python
from vikhry import ParallelReadyStrategy, VU


class DemoVU(VU):
    step_strategy = ParallelReadyStrategy()
```

`ParallelReadyStrategy` runs all ready steps in the same scheduling tick instead of choosing only one.

You can also provide your own object implementing `select(...)` with the `StepStrategy` protocol.
