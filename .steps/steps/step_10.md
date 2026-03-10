# Step 10: Тестирование и стабилизация v1

## Цель

Добавить покрытие тестами для ключевых частей orchestrator:
- контракты команд;
- allocator и lifecycle state machine;
- worker presence rules;
- интеграции с реальным Redis (docker);
- edge-cases по отказам и идемпотентности.

## Реализация

[x] Unit tests:
  - `tests/unit/test_command_models.py`
  - `tests/unit/test_user_orchestration.py`
  - `tests/unit/test_worker_presence_service.py`
  - `tests/unit/test_lifecycle_service.py`
[x] Integration tests (dockerized Redis):
  - `tests/integration/conftest.py`
  - `tests/integration/test_lifecycle_integration.py`
[x] Покрыты edge/resilience кейсы:
  - отсутствие alive worker'ов при `start_test`;
  - просроченный heartbeat;
  - duplicate `add/remove` операции (идемпотентность);
  - rollback состояния при ошибке старта.
[x] Обновлена пользовательская документация по запуску тестов (`README.md`).
[ ] Structured logging и отдельные orchestrator internal runtime metrics
    (latency API, rate команд, ошибки) остаются отдельным финальным подшагом.

## Прогон тестов

`uv run pytest -q`  
Результат: `14 passed`.

