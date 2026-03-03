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

# Worker v1 Description

Цель: реализовать `worker` для v1 в поэтапной модели (control-plane MVP -> runtime сценариев):
- итерация 1: только control-plane (команды, heartbeat, lifecycle, CLI), без исполнения нагрузочного DSL;
- итерация 2: запуск реальных VU сценариев и публикация метрик нагрузки.

Зафиксированные решения:
- обработка команд строго по очереди в одном event loop (single-threaded dispatcher);
- `epoch` переключается только на `start_test`;
- для согласованности изменить порядок команд orchestrator на `start_test -> add_user`;
- `start_test` в worker на этапе MVP выполняет только переключение локального состояния (заглушка);
- graceful stop с таймаутом и fallback в принудительное завершение локальных задач;
- `worker_id` автогенерируется при старте как короткий id (`uuid4().hex[:8]`);
- в MVP нет синтетических и внутренних метрик worker, только healthcheck в Redis.

Технологический стек:
- Python 3.14
- asyncio + uvloop
- redis.asyncio
- orjson
- Typer

# Worker v1 Implementation

## Step 11: Каркас worker процесса и настройки
[x] Создать модульную структуру `vikhry/worker` (`app`, `models`, `services`, `redis_repo`).
[x] Добавить `WorkerSettings` и bootstrap процесса (uvloop, Redis, graceful shutdown hooks).
[x] Переиспользовать command contract (`CommandEnvelope`, payload-модели) без дублирования схем.
[x] Ввести локальное состояние worker (`phase`, `current_epoch`, `assigned_users`).

## Step 12: Регистрация worker и heartbeat
[x] При старте регистрировать worker в `workers` и публиковать `worker:{id}:status`.
[x] Реализовать heartbeat loop с обновлением `status=healthy` и `last_heartbeat`.
[x] На штатной остановке выполнять unregister (`workers`, `worker:{id}:status`, `worker:{id}:users`).
[x] Добавить best-effort перевод в `unhealthy` перед shutdown.

## Step 13: Command loop и epoch-gating
[x] Подписка на персональный канал `worker:{worker_id}:commands` через Redis Pub/Sub.
[x] Реализовать последовательный dispatcher (команды обрабатываются строго по одной).
[x] Правила epoch: `start_test` с большим epoch переключает эпоху; команды со старым epoch игнорируются.
[x] Для невалидного JSON и неизвестного `type` делать ignore + лог (без падения процесса).

## Step 14: Обработчики команд (MVP без VU runtime)
[x] `start_test`: идемпотентно переводить worker в `RUNNING` (заглушка без запуска VU).
[x] `add_user`: идемпотентно обновлять локальный набор назначенных пользователей.
[x] `remove_user`: идемпотентно удалять пользователя из локального набора.
[x] `stop_test`: выполнять graceful stop с таймаутом, очищать локальное состояние и переходить в `IDLE`.

## Step 15: CLI-интеграция worker
[x] Добавить группу `vikhry worker` в Typer.
[x] Реализовать `vikhry worker start` с режимами `--detach/--foreground`.
[x] Добавить PID/log/startup контроль, совместимый с паттерном orchestrator CLI.
[x] Реализовать `vikhry worker stop` с каскадом сигналов (`SIGINT -> SIGTERM -> SIGKILL --force`).

## Step 16: Генерация и идентификация worker_id
[x] По умолчанию генерировать короткий `worker_id` (`uuid4().hex[:8]`).
[x] Выводить `worker_id` в CLI/log при старте для операционной диагностики.
[x] Гарантировать использование одного `worker_id` во всех Redis ключах текущего процесса.
[ ] Задокументировать формат id и возможные коллизии (best-effort, редкий случай).

## Step 17: Совместимость orchestrator <-> worker
[x] Изменить lifecycle orchestrator: отправка `start_test` перед серией `add_user`.
[x] Обновить unit/integration тесты orchestrator под новый порядок доставки команд.
[ ] Проверить идемпотентность при повторных `start_test/add_user/remove_user/stop_test`.
[x] Синхронизировать docs/contracts с фактическим порядком команд.

## Step 18: Тестирование worker MVP и документация
[x] Unit tests для command dispatcher, epoch-gating и идемпотентных обработчиков.
[x] Integration tests с Redis: регистрация heartbeat, обработка команд, graceful stop.
[x] E2E smoke: orchestrator + worker + CLI (`start/change-users/stop`) без падений и рассинхрона.
[x] Обновить README и `docs/3_worker.md` под реализованный MVP и ограничения (без DSL runtime).

# UI v1 Description

Цель: реализовать production-ready web UI для управления тестом и live-наблюдения метрик с учетом ограничений v1.

Зафиксированные решения:
- frontend как отдельное React + TypeScript + Vite приложение;
- маршрутизация через React Router с отдельными route на вкладки (`/stats`, `/charts`, `/resources`, `/workers`);
- `react-query` используется для server-state, `MobX` — для UI/runtime состояния и live-сессии;
- live-данные приходят push-only через `ws /ws/metrics` (HTTP только для bootstrap и non-live endpoints);
- перцентили (`median`, `p95`, `p99`) считаются в orchestrator;
- расчет перцентилей exact (по всем latency sample в окне агрегации);
- orchestrator расширяется новыми API для UI: `/workers`, `/resources`.

Технологический стек:
- React + TypeScript + Vite
- React Router
- DaisyUI
- @tanstack/react-query
- MobX / mobx-react-lite
- Recharts

# UI v1 Implementation

## Step 19: API-контракты для UI
[x] Добавить `GET /workers` с полями `worker_id`, `status`, `last_heartbeat`, `heartbeat_age_s`, `users_count`.
[x] Добавить `GET /resources` с полями `resource_name`, `count`.
[x] Зафиксировать и задокументировать JSON-контракты новых endpoints в `docs/contracts/v1.md`.
[x] Добавить unit/integration тесты для `/workers` и `/resources`.

## Step 20: Расширение метрик (exact percentiles)
[x] Обновить `MetricsService` для расчета `latency_median_ms`, `latency_p95_ms`, `latency_p99_ms` в окне `window_s`.
[x] Добавить новые поля в `aggregate` ответа `/metrics` и payload `metrics_snapshot`/`metrics_tick`.
[x] Сохранить backward compatibility по текущим полям (`requests`, `errors`, `error_rate`, `rps`, `latency_avg_ms`).
[x] Покрыть тестами корректность расчетов перцентилей (четное/нечетное число sample, пустое окно).

## Step 21: Каркас frontend приложения
[ ] Создать директорию `frontend/` и инициализировать Vite React TypeScript проект.
[ ] Подключить DaisyUI и базовый дизайн-токены слой (цвета, типографика, spacing).
[ ] Настроить React Router с layout и route-страницами: `stats`, `charts`, `resources`, `workers`.
[ ] Добавить конфиг окружения для API base URL и WebSocket URL.

## Step 22: Data layer и live-сессия
[ ] Реализовать API client для orchestrator endpoints (`/ready`, `/start_test`, `/stop_test`, `/change_users`, `/scenario/on_init_params`, `/metrics`, `/workers`, `/resources`, `/create_resource`, `/ensure_resource`).
[ ] Настроить `react-query` для REST-запросов и инвалидаций после mutation.
[ ] Реализовать MobX store для WebSocket live-сессии (`connect`, `reconnect`, `backoff`, `last_tick_at`, `is_live`).
[ ] Реализовать merge live-payload в клиентские модели для таблиц и графиков без polling.

## Step 23: Header и управление запуском теста
[ ] Собрать верхнюю control-панель: `state`, `epoch`, `alive_workers`, lag/backlog indicators.
[ ] Реализовать Start/Stop/Change Users действия с обработкой API ошибок.
[ ] Построить динамическую форму `init_params` на основе `/scenario/on_init_params`.
[ ] Добавить guard'ы UI по state machine (`start` только из `IDLE`, `change_users` только в `RUNNING`).

## Step 24: Вкладка Stats
[ ] Реализовать таблицу метрик с группировкой по `metric_id`.
[ ] Показать `requests`, `errors`, `error_rate`, `rps`, `latency_avg_ms`, `latency_median_ms`, `latency_p95_ms`, `latency_p99_ms`.
[ ] Добавить выбор видимых колонок и сохранить пользовательский выбор (local storage).
[ ] Добавить сортировку и фильтрацию по имени метрики.

## Step 25: Вкладка Charts
[ ] Реализовать ring-buffer временных рядов на клиенте (интервалы 5m/15m/30m/1h).
[ ] Построить графики Recharts для `rps`, `latency`, `errors/error_rate`.
[ ] Добавить выбор отображаемых метрик и серий.
[ ] Добавить обработку деградации live-потока (stale banner/indicator).

## Step 26: Вкладки Resources и Workers
[ ] Resources: список ресурсов (`name`, `count`) + модальное окно create/ensure count.
[ ] Workers: таблица worker'ов со статусом, возрастом heartbeat и числом назначенных users.
[ ] Добавить действия refresh/retry и состояния empty/error/loading.
[ ] Синхронизировать данные вкладок после mutation операций.

## Step 27: Тестирование, документация, стабилизация
[ ] Добавить frontend unit tests для store/formatters и базовых UI-сценариев.
[ ] Добавить integration тесты orchestrator для расширенного контракта метрик и новых endpoints.
[ ] Обновить `README.md` и `docs/5_ui.md` по фактической архитектуре и UX-flow.
[ ] Добавить smoke-checklist запуска UI вместе с orchestrator/worker.

# Error Telemetry v1 Description

Цель: унифицировать обработку ошибок и исходов выполнения в едином потоке метрик, чтобы:
- прозрачно видеть падения lifecycle (`on_init`, `on_start`) и исключения в step/runtime;
- агрегировать результат выполнения по универсальным кодам исхода (`result_code`) без жесткого whitelist;
- поддержать не только HTTP, но и будущие клиенты (например JsonRPC с ошибками в payload);
- отобразить в UI breakdown по `result_code`/категориям без взрывного роста кардинальности.

Принятые решения:
- ошибки остаются в том же потоке, что и метрики (не в отдельном канале);
- `result_code` — произвольная строка, но с нормализацией и ограничением длины/символов;
- агрегатор считает top-K кодов + `OTHER`, чтобы сдерживать объем данных и сложность UI;
- детальный stacktrace хранится в логах worker, в метриках — краткая выжимка (`error_type`, `error_message`).

# Error Telemetry v1 Implementation

## Step 28: Унифицированный контракт outcome-метрик
[x] Расширить payload метрики полями: `source`, `stage`, `result_code`, `result_category`, `fatal`, `error_type`, `error_message`.
[x] Реализовать нормализацию `result_code` (uppercase, безопасные символы, ограничение длины, fallback `UNKNOWN`).
[x] Зафиксировать правила low-cardinality (без динамических идентификаторов и длинных текстов в `result_code`).
[x] Добавить unit-тесты на валидацию/нормализацию и совместимость с существующими полями (`name`, `step`, `status`, `time`).

## Step 29: Runtime-эмиттеры и backend-агрегация ошибок
[x] В `run_user` добавить эмиссию lifecycle-метрик при падении `on_init`/`on_start` (`fatal=true`, без запуска step).
[x] В step-метриках добавить outcome-коды (`STEP_OK`/`STEP_EXCEPTION`) и категории.
[x] В HTTP-клиенте добавить унифицированные outcome-коды (`HTTP_<status>`, `HTTP_EXCEPTION`) и категории ошибок.
[x] Расширить `MetricsService` новыми агрегатами: `result_code_counts`, `result_category_counts`, `fatal_count`, `top_result_codes` (+`OTHER`).
[x] Обновить контракт `/metrics` и документацию `docs/contracts/v1.md`.

## Step 30: UI breakdown и операционная видимость
[ ] Добавить в UI блок breakdown по `result_code` и `result_category`.
[ ] Добавить отдельный индикатор/блок для `fatal` lifecycle ошибок (`on_init`/`on_start`).
[ ] Добавить переключение/фильтры для просмотра ошибок по source (`lifecycle`, `step`, `http`, будущие клиенты).
[ ] Ограничить отображение редких кодов (top-K + `OTHER`) для стабильной читаемости.
[ ] Добавить frontend и integration тесты на новые поля метрик и визуализацию breakdown.
