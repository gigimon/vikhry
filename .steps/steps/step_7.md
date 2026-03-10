# Step 7: HTTP API orchestrator (Option C)

## Цель

Реализовать HTTP API v1 поверх сервисного слоя:
- `/start_test`
- `/stop_test`
- `/change_users`
- `/create_resource`
- `/metrics`

С единым форматом ошибок и без WebSocket на этом этапе (перенос в следующий шаг).

## Выбранный вариант

Option C: сначала только HTTP, WebSocket отложен.

## Реализация

[x] Добавлены API request-модели:
  - `StartTestRequest`
  - `ChangeUsersRequest`
[x] Добавлен `MetricsService` для HTTP чтения метрик.
[x] Добавлены HTTP endpoints:
  - `POST /start_test`
  - `POST /change_users`
  - `POST /stop_test`
  - `POST /create_resource`
  - `GET /metrics`
[x] Добавлен единый формат ошибок:
  - `invalid_json`
  - `validation_error`
  - `invalid_state`
  - `no_alive_workers`
  - `bad_request`
  - `internal_error`
[x] Поддержаны алиасы payload:
  - `users -> target_users` для `/start_test` и `/change_users`.

## Наблюдения

1. `health` и `ready` уже были реализованы ранее, дополнительных изменений не потребовалось.
2. WebSocket поток live-метрик намеренно не добавлялся в рамках выбранного Option C.
3. Текущий `/metrics` возвращает сырые события по streams; агрегация будет реализована на следующем шаге.

