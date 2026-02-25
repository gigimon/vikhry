# vikhry

Асинхронный распределенный фреймворк для нагрузочного тестирования.

## CLI

Основные команды:

```bash
uv run vikhry orchestrator start --host 127.0.0.1 --port 8080 --redis-url redis://127.0.0.1:6379/0
uv run vikhry test start --users 100 --orchestrator-url http://127.0.0.1:8080
uv run vikhry test change-users --users 150 --orchestrator-url http://127.0.0.1:8080
uv run vikhry test stop --orchestrator-url http://127.0.0.1:8080
uv run vikhry orchestrator stop
```

По умолчанию `orchestrator start` запускает процесс в фоне (detach) и освобождает терминал.
Для запуска в текущем терминале используйте `--foreground`.

## Тесты

Unit + integration:

```bash
uv run pytest -q
```

Только integration (нужен Docker):

```bash
uv run pytest -m integration tests/integration -q
```
