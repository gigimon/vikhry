# Step 11: Worker MVP foundation (control-plane)

## Цель

Запустить первую рабочую версию `worker` для v1-контракта без исполнения DSL-сценариев:
- регистрация и heartbeat в Redis;
- последовательная обработка команд из персонального канала;
- strict epoch-gating с переключением только на `start_test`;
- CLI-управление жизненным циклом worker (`start/stop`, detach/foreground).

## Реализация

[x] Добавлен пакет `vikhry/worker`:
  - `vikhry/worker/app.py`
  - `vikhry/worker/models/*`
  - `vikhry/worker/redis_repo/*`
  - `vikhry/worker/services/*`
[x] Реализован bootstrap worker:
  - `uvloop` + async runtime;
  - подключение Redis;
  - graceful shutdown по `SIGINT`/`SIGTERM`.
[x] Реализованы registration + heartbeat:
  - `workers` registry;
  - `worker:{id}:status` с `healthy/unhealthy` и `last_heartbeat`;
  - unregister на остановке.
[x] Реализован command loop (single-threaded):
  - подписка `worker:{worker_id}:commands`;
  - ignore invalid JSON/unknown type;
  - обработчики `start_test`, `stop_test`, `add_user`, `remove_user`.
[x] Реализован MVP lifecycle:
  - `start_test` переводит worker в `RUNNING` (заглушка без VU runtime);
  - `add/remove_user` идемпотентно обновляют локальный набор пользователей;
  - `stop_test` делает graceful stop локальных задач с timeout и очищает состояние.
[x] Добавлена CLI-интеграция:
  - `vikhry worker start`
  - `vikhry worker stop`
  - hidden `vikhry worker serve` для detach режима;
  - авто-генерация short `worker_id` (`uuid4().hex[:8]`).
[x] Для совместимости с выбранной epoch-моделью изменен порядок команд в orchestrator:
  - `start_test` отправляется перед `add_user`.

## Прогон проверок

`uv run pytest -q`  
Результат: `14 passed`.

`uv run python -m vikhry.cli --help`  
Результат: CLI включает новую группу `worker`.
