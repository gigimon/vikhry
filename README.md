# vikhry

Async distributed load-testing framework (coordinator + worker) with Redis coordination.

## Frontend UI

`frontend/` содержит SPA dashboard для управления тестом и live-метрик.

Запуск:

```bash
cd frontend
npm install
npm run dev
```

По умолчанию UI ожидает coordinator на `http://127.0.0.1:8080` и API prefix `/api/v1` (можно менять в верхней панели).

Что уже есть в UI:
- создание теста из формы;
- операции `start_preparing`, `start_running`, `scale`, `stop`;
- live WebSocket метрики (`/ws/tests/metrics?test_id=...`);
- мониторинг статуса теста и последней операции.

## CLI

После `uv sync` доступны команды (`vikhryctl`), либо можно запускать модуль напрямую `uv run python -m vikhry.cli ...`.

1. Запуск orchestrator (coordinator API):

```bash
uv run vikhryctl orchestrator --redis-url redis://127.0.0.1:6379/0 --host 127.0.0.1 --port 8080
```

2. Запуск worker:

```bash
uv run vikhryctl worker --redis-url redis://127.0.0.1:6379/0 --test-id dsl-smoke
```

3. Создание теста + start_preparing + (опционально) ожидание READY + start_running:

```bash
uv run vikhryctl test start \
  --coordinator-url http://127.0.0.1:8080 \
  --config /absolute/path/to/test-config.json
```

Флаги `test start`:
- `--no-wait-ready` чтобы не ждать `READY`;
- `--no-start-running` чтобы сделать только create + preparing;
- `--target-vu N` override для payload `start-running`.

## DSL scenario support

Worker can load user scenario classes/resources declared via:

- `vikhry.dsl.BaseVU`
- `vikhry.dsl.step`
- `vikhry.dsl.resource`

Example scenario: `examples.http_smoke_scenario:HttpSmokeScenario`.

### Create test with DSL scenario

Use coordinator API `POST /api/v1/tests` with:

- `scenario_module`: Python module path (`examples.http_smoke_scenario`)
- `scenario_class`: class name (`HttpSmokeScenario`)
- `context`: arbitrary JSON object available in VU as `self.context["config_context"]`

Example body:

```json
{
  "test_id": "dsl-smoke",
  "name": "dsl-smoke",
  "scenario_module": "examples.http_smoke_scenario",
  "scenario_class": "HttpSmokeScenario",
  "context": {
    "target_url": "https://httpbin.org/get"
  },
  "profile": {"mode": "constant", "target_vu": 10, "target_rps": null, "duration_s": 60, "ramp_up_s": 5},
  "limits": {"max_in_flight": 100, "max_connections": 50, "request_timeout_ms": 3000, "step_timeout_ms": 5000, "retry_max": 1},
  "preparing": {"timeout_s": 30, "resource_targets": [{"kind": "users", "count": 10, "concurrency": 2, "batch_size": 5}]},
  "running": {"graceful_stop_timeout_s": 10},
  "operations": {"timeout_s": 30},
  "redis": {"url": "redis://localhost:6379/0", "stream_block_ms": 100}
}
```
