# Step 2: Контракты и Redis-слой

## Цель

Закрыть контрактный слой orchestrator v1:
- строгие модели команд и статусов;
- полный Redis repository для keyspace v1;
- атомарные операции lifecycle;
- сериализация/десериализация команд через `orjson`.

## Выбранный подход

Выбран вариант `B`: использовать `Pydantic` для валидации контрактов и типизации payload'ов.

Причины:
1. Строгая валидация входных данных команд.
2. Явные ошибки контракта при парсинге.
3. Централизация схемы в моделях.

## Реализация

[x] Добавлена зависимость `pydantic`.
[x] Реализованы модели:
  - `CommandType`, `CommandEnvelope`
  - `StartTestPayload`, `StopTestPayload`, `AddUserPayload`, `RemoveUserPayload`
  - `WorkerHealthStatus`, `WorkerStatus`
  - `UserRuntimeStatus`, `UserAssignment`
[x] Реализована сериализация команд:
  - `CommandEnvelope.to_json_bytes()`
  - `CommandEnvelope.from_json_bytes()`
[x] Расширен Redis repository (`TestStateRepository`) до keyspace v1:
  - `test:*`
  - `workers`, `worker:*:status`, `worker:*:users`, `worker:*:commands`
  - `users`, `user:*`
  - `resources`, `resource:{name}:{id}`
  - `metrics`, `metric:{metric_id}`
[x] Добавлены атомарные операции:
  - compare-and-set для `test:state` через Lua
  - атомарный переход `IDLE -> PREPARING` с `epoch++` через Lua

## Наблюдения

1. Репозиторий теперь покрывает все основные v1-операции хранения и pub/sub.
2. Детали бизнес-правил state machine останутся в lifecycle service (Step 5), а не в Redis-слое.

