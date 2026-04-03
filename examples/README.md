# Examples

Example scenario with 2 resources (`users`, `sessions`) and HTTP steps:
- `auth` -> `http://localhost:8000/auth`
- `page1` -> `http://localhost:8000/page1` (depends on `auth`)
- `page2` -> `http://localhost:8000/page2`
- `page3` -> `http://localhost:8000/page3`
- `page2_health` probe -> `http://localhost:8000/page2`

`every_s` is configured via `between(min, max)` callbacks, so delays between
step runs are randomized per execution.

The example also includes a module-level probe:

```python
@probe(name="page2_health", every_s=5.0, timeout=2.0)
async def page2_health_probe() -> int:
    ...
```

It polls `/page2` once every 5 seconds, fails on HTTP `>= 400`, and publishes
the latest status code to the probe stream.

Scenario import path:

```bash
examples.scenarios.localhost_demo:LocalhostDemoVU
```

Run worker with this scenario:

```bash
uv run vikhry worker start \
  --run-probes \
  --scenario examples.scenarios.localhost_demo:LocalhostDemoVU
```

`base_url` is required by `LocalhostDemoVU.on_init`, so pass it when starting test:

```bash
uv run vikhry test start \
  --users 10 \
  --init-param base_url=http://localhost:8000
```

After the run starts, open the dedicated probe page at `#/probes` in the UI to
see the `page2_health` graph.
