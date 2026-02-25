# Examples

Example scenario with 2 resources (`users`, `sessions`) and HTTP steps:
- `auth` -> `http://localhost:8000/auth`
- `page1` -> `http://localhost:8000/page1` (depends on `auth`)
- `page2` -> `http://localhost:8000/page2`
- `page3` -> `http://localhost:8000/page3`

Scenario import path:

```bash
examples.scenarios.localhost_demo:LocalhostDemoVU
```

Run worker with this scenario:

```bash
uv run vikhry worker start \
  --scenario examples.scenarios.localhost_demo:LocalhostDemoVU
```

