# vikhry

Асинхронный распределенный фреймворк для нагрузочного тестирования.

## Текущий статус

Реализован v1 orchestrator и worker runtime.

Что уже работает:
- lifecycle теста `IDLE -> PREPARING -> RUNNING -> STOPPING -> IDLE`;
- управление пользователями через `start/change-users/stop`;
- персональные команды worker через Redis Pub/Sub;
- worker heartbeat (`worker:{worker_id}:status`);
- исполнение `VU`-сценариев в worker (`@step`, weighted выбор, `requires`, `every_s`, `timeout`);
- HTTP вызовы в VU через `pyreqwest`;
- публикация событий нагрузки из worker в `metric:{metric_id}` streams;
- CLI для orchestrator, worker и test-команд;
- E2E smoke с проверкой согласованности Redis keyspace.

Что пока не реализовано:
- provisioning pipeline для автоматического наполнения ресурсов через `@resource`-фабрики;
- расширенная агрегация latency (p95/p99) на стороне orchestrator.

## CLI

Основные команды:

```bash
uv run vikhry orchestrator start --host 127.0.0.1 --port 8080 --redis-url redis://127.0.0.1:6379/0
uv run vikhry orchestrator start --scenario /path/to/scenario.py
uv run vikhry worker start --redis-url redis://127.0.0.1:6379/0
uv run vikhry worker start --scenario my_load.scenarios:MyVU --http-base-url https://api.example.com
uv run vikhry test start --users 100 --orchestrator-url http://127.0.0.1:8080
uv run vikhry test start --users 100 --init-param tenant=demo --init-param warmup=3
uv run vikhry test change-users --users 150 --orchestrator-url http://127.0.0.1:8080
uv run vikhry test stop --orchestrator-url http://127.0.0.1:8080
uv run vikhry worker stop
uv run vikhry orchestrator stop
```

По умолчанию `orchestrator start` и `worker start` запускают процесс в фоне (detach) и освобождают терминал.
Для запуска в текущем терминале используйте `--foreground`.
Опция `orchestrator --scenario /path/to/scenario.py` читает `@resource(...)` декларации из файла сценария.
В фазе `PREPARING` orchestrator создает недостающие ресурсы под `target_users` (on-demand).
По умолчанию `pid` и `log` сохраняются в системный runtime-каталог:
- macOS: `~/Library/Caches/vikhry/`
- Linux: `$XDG_RUNTIME_DIR/vikhry/` (или `/run/user/<uid>/vikhry/`, fallback `/tmp/vikhry/`)

## Зафиксированные решения worker MVP

- Команды обрабатываются строго последовательно (single-threaded command dispatcher).
- Переключение `epoch` у worker происходит только по `start_test`.
- Для согласованности orchestrator отправляет `start_test` перед серией `add_user`.
- `start_test` переводит worker в `RUNNING`, а `add_user` создает отдельную async VU-задачу.
- Worker публикует step-события в `metric:worker:{worker_id}` для live-агрегации.
- `worker_id` по умолчанию генерируется автоматически (`uuid4().hex[:8]`), можно передать через `--worker-id`.
- В логах worker есть события: startup, подключение к Redis, получение command envelope.

## Тесты

Unit + integration:

```bash
uv run pytest -q
```

Только integration (нужен Docker):

```bash
uv run pytest -m integration tests/integration -q
```

UI может получить параметры `VU.on_init` через `GET /scenario/on_init_params`,
а затем передать их в `POST /start_test` как `init_params`.

На текущем состоянии: `45 passed` (`uv run pytest -q`).
