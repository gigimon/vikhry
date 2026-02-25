# Step 18: Тестирование worker MVP и документация

## Цель

Добавить покрытие тестами для worker MVP (control-plane), чтобы зафиксировать:
- корректную последовательную обработку команд;
- strict epoch-gating;
- идемпотентность операций над пользователями;
- heartbeat-контракт в Redis.

## Реализация

[x] Unit tests:
  - `tests/unit/test_worker_command_dispatcher.py`
  - `tests/unit/test_worker_heartbeat_service.py`
[x] Integration tests (dockerized Redis):
  - `tests/integration/test_worker_services_integration.py`
[x] Покрытые сценарии:
  - `start_test -> add_user/remove_user -> stop_test` для dispatcher;
  - игнорирование невалидного JSON в command loop;
  - игнор stale команд по `epoch`;
  - идемпотентность duplicate `add_user`/`remove_user`;
  - публикация `healthy/unhealthy` heartbeat в `worker:{id}:status`.
[x] E2E smoke orchestrator + worker + CLI:
  - старт orchestrator/worker через CLI;
  - проверка ready/alive в orchestrator;
  - прогон `test start -> change-users -> stop`;
  - проверка Redis keyspace (`workers`, `worker:*:status`, `users`, `user:*`, `test:state`).
[x] Обновлена пользовательская документация:
  - `README.md`
  - `docs/3_worker.md`
  - синхронизированы `docs/0_cli.md`, `docs/2_orchestrator.md`, `docs/contracts/v1.md`.

## Прогон проверок

`uv run pytest -q`  
Результат: `23 passed`.
