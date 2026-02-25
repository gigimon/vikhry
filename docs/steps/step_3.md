# Step 3: Мониторинг worker'ов

## Цель

Реализовать определение alive worker'ов для orchestrator v1:
- alive только при `status=healthy`;
- heartbeat не должен быть просрочен;
- порядок worker'ов должен быть детерминированным;
- отсутствие alive worker'ов должно обрабатываться явно.

## Выбранное правило alive (Option A)

Worker считается alive, если одновременно:
1. `worker:{worker_id}:status.status == healthy`;
2. `now - last_heartbeat <= heartbeat_timeout_s`.

## Реализация

[x] Добавлен `WorkerPresenceService`:
  - `list_alive_workers()`
  - `refresh_cache()`
  - `cached_alive_workers()`
  - `require_alive_workers()`
[x] Добавлена доменная ошибка `NoAliveWorkersError` для операций, которым нужны alive worker'ы.
[x] Подключен периодический мониторинг:
  - `WorkerMonitor` выполняет `on_tick=worker_presence.refresh_cache`.
  - Ошибки `on_tick` логируются и не роняют monitor loop.
[x] Зафиксирован стабильный порядок worker'ов через сортировку в Redis repository.
[x] Расширен `/ready`:
  - `alive_workers` (count)
  - `workers` (список worker_id из кеша мониторинга)

## Наблюдения

1. Этот шаг дает опорный слой для Step 4/5, где lifecycle-операции должны валидировать наличие alive worker'ов.
2. На текущем этапе `require_alive_workers()` подготовлен для интеграции в `start_test`/`change_users`.

