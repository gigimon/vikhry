# Quickstart

## Install

```bash
pip install vikhry
```

## Start local infrastructure

```bash
vikhry infra up \
  --worker-count 3 \
  --scenario my_scenario:DemoVU
```

What this does:
- checks Docker CLI and daemon availability;
- starts Redis in the `vikhry-redis-infra` container;
- starts the orchestrator on `http://127.0.0.1:8080`;
- starts the requested number of workers.

After startup:
- UI: `http://127.0.0.1:8080/`
- API: `http://127.0.0.1:8080`

## Stop local infrastructure

```bash
vikhry infra down
```

## Build Python artifacts locally

```bash
./scripts/build_frontend.sh
uv build
```

If `frontend/dist` is missing, `wheel` and `sdist` builds will fail.
