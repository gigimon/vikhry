# Step 19: API-контракты для UI

## Цель

Подготовить backend-контракты для вкладок UI `Workers` и `Resources`:
- добавить отдельные endpoints чтения `/workers` и `/resources`;
- стабилизировать JSON-ответы для frontend;
- покрыть изменения unit/integration тестами.

## Реализация

[x] Добавлен endpoint `GET /workers` в orchestrator API:
  - возвращает `generated_at`, `count`, `workers[]`;
  - каждый worker содержит `worker_id`, `status`, `last_heartbeat`, `heartbeat_age_s`, `users_count`;
  - поддерживает `null` для status/heartbeat полей, если worker зарегистрирован без published health status.
[x] Добавлен endpoint `GET /resources` в orchestrator API:
  - возвращает `generated_at`, `count`, `resources[]`;
  - список включает пары `resource_name` + `count` из Redis hash `resources`.
[x] Обновлен wiring роутов:
  - `register_routes(...)` теперь получает `state_repo` и использует его для snapshot endpoint'ов.
[x] Обновлена контрактная документация:
  - `docs/contracts/v1.md` дополнен секцией `Orchestrator HTTP API (v1)`;
  - добавлены примеры и описание ответов `/workers` и `/resources`.
[x] Добавлены тесты:
  - unit: `tests/unit/test_orchestrator_api_routes.py`;
  - integration: `tests/integration/test_orchestrator_api_endpoints.py`.

## Прогон проверок

- `uv run pytest tests/unit/test_orchestrator_api_routes.py -q` -> `2 passed`
- `uv run pytest tests/integration/test_orchestrator_api_endpoints.py -q` -> `1 passed`
- `uv run ruff check vikhry/orchestrator/api/routes.py vikhry/orchestrator/app.py tests/unit/test_orchestrator_api_routes.py tests/integration/test_orchestrator_api_endpoints.py` -> `All checks passed!`
