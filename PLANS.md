# Description

Цель: реализовать `orchestrator` для vikhry v1 как центральный управляющий компонент, который:
- управляет lifecycle теста (`IDLE -> PREPARING -> RUNNING -> STOPPING -> IDLE`);
- координирует worker'ов через Redis Pub/Sub (персональные каналы);
- распределяет пользователей по alive worker'ам через round-robin;
- предоставляет HTTP/WebSocket API для CLI/UI;
- работает в рамках ограничений v1 (без `run_id`, без `ack/nack`, один активный тест).

Технологический стек:
- Python 3.14
- asyncio + uvloop
- Robyn (HTTP + WebSocket)
- redis.asyncio
- orjson
- pyreqwest (клиент для CLI и внутренних HTTP-вызовов при необходимости)

Ключевые ограничения из контракта:
- runtime-конфиг только через CLI, без конфигурационных файлов;
- команды worker'ам только в `worker:{worker_id}:commands`;
- ресурсы не очищаются автоматически на `stop_test`;
- масштабирование пользователей только через `add_user`/`remove_user`.

# Implementation

## Step 1: Каркас orchestrator процесса
[x] Создать модульную структуру orchestrator (`app`, `api`, `services`, `redis_repo`, `models`).
[x] Реализовать bootstrap: запуск uvloop, подключение к Redis, инициализация Robyn.
[x] Добавить базовую инициализацию ключей `test:state` и `test:epoch`.
[x] Добавить graceful shutdown (закрытие Redis, остановка фоновых задач).

## Step 2: Контракты и Redis-слой
[x] Описать типы/модели: `TestState`, `WorkerStatus`, `CommandEnvelope`, payload'ы команд.
[x] Реализовать Redis repository для keyspace v1 (`test:*`, `workers`, `worker:*`, `users`, `user:*`, `resources`, `metrics`).
[x] Добавить атомарные операции для смены состояния теста и инкремента эпохи.
[x] Добавить сериализацию/десериализацию команд через `orjson`.

## Step 3: Мониторинг worker'ов
[x] Реализовать сервис определения alive worker'ов по `worker:{id}:status.last_heartbeat`.
[x] Ввести heartbeat timeout и период фоновой проверки.
[x] Добавить стабильную сортировку worker'ов для детерминированного round-robin.
[x] Покрыть сценарии отсутствия alive worker'ов (ошибка запуска/масштабирования).

## Step 4: Оркестрация пользователей и команд
[x] Реализовать allocator `round-robin` для назначения `user_id -> worker_id`.
[x] Реализовать publisher команд `add_user`, `remove_user`, `start_test`, `stop_test` в персональные каналы.
[x] Реализовать запись назначений в `users`, `user:{id}`, `worker:{id}:users`.
[x] Обеспечить идемпотентность операций на стороне orchestrator (повторные запросы не ломают состояние).

## Step 5: Lifecycle manager (`start_test`, `change_users`, `stop_test`)
[x] Реализовать state guards: разрешенные переходы и ошибки при нарушении state machine.
[x] `start_test`: `PREPARING`, `epoch++`, подготовка ресурсов, `add_user`, `start_test`, переход в `RUNNING`.
[x] `change_users`: вычисление дельты и отправка серии `add_user`/`remove_user` только в `RUNNING`.
[x] `stop_test`: переход в `STOPPING`, отправка `stop_test`, очистка пользовательских ключей, возврат в `IDLE`.

## Step 6: Ресурсы и подготовительная фаза
[x] Реализовать сервис подготовки ресурсов в фазе `PREPARING`.
[x] Поддержать запись `resources` и `resource:{resource_name}:{id}`.
[x] Зафиксировать политику v1: дубли ресурсов допустимы, автоочистки нет.
[x] Добавить API-операцию `/create_resource` с валидацией входных данных.

## Step 7: HTTP/WebSocket API orchestrator
[x] Реализовать HTTP endpoints v1: `/start_test`, `/stop_test`, `/change_users`, `/create_resource`, `/metrics`.
[x] Добавить единый формат ошибок (state violation, no workers, invalid payload).
[x] Реализовать WebSocket поток live-метрик для UI.
[x] Добавить health/readiness endpoint orchestrator для операционного контроля.

## Step 8: Метрики и агрегация
[x] Реализовать чтение из `metric:{metric_id}` streams и публикацию в API/WebSocket.
[x] Добавить минимальную агрегацию (RPS, latency, errors) с ограничением памяти.
[x] Реализовать контроль backlog/lag для защиты от перегрузки.
[x] Подготовить контракт ответа `/metrics` для UI/CLI.

## Step 9: CLI-интеграция
[x] Реализовать команды `vikhry orchestrator start/stop` (Typer).
[x] Реализовать команды `vikhry test start/stop/change-users` через HTTP к orchestrator.
[x] Передавать все runtime-параметры только через CLI-флаги.
[x] Добавить валидацию и дружелюбные сообщения об ошибках CLI.

## Step 10: Тестирование и стабилизация v1
[x] Написать unit-тесты для allocator, state machine, валидации команд.
[x] Написать integration-тесты с Redis (start/change/stop happy path + edge cases).
[x] Проверить отказоустойчивость: нет worker'ов, просроченный heartbeat, дублирующие команды.
[ ] Добавить structured logging и базовые метрики orchestrator (latency API, rate команд, ошибки).
[x] Обновить `README.md` и `docs/` с фактическим поведением реализации.
