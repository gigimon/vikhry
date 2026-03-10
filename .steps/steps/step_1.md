# Step 1: Каркас orchestrator процесса

## Цель

Собрать минимально рабочий каркас orchestrator, чтобы в следующих шагах добавлять бизнес-логику без переделки bootstrap-слоя.

## Принятые решения

1. Использовать пакетную структуру:
   - `vikhry/orchestrator/app.py`
   - `vikhry/orchestrator/api/`
   - `vikhry/orchestrator/services/`
   - `vikhry/orchestrator/redis_repo/`
   - `vikhry/orchestrator/models/`
2. Инициализацию event loop выполнять через `uvloop.install()` перед запуском Robyn.
3. Инициализацию Redis-ключей (`test:state`, `test:epoch`) выполнять в `startup_handler`.
4. Graceful shutdown выполнять через `shutdown_handler`:
   - остановка фоновых задач;
   - закрытие Redis клиента.
5. Для проверки жизнеспособности каркаса добавить технические endpoint'ы:
   - `GET /health`
   - `GET /ready`

## Реализация

[x] Создан пакет `vikhry` и подпакет orchestrator.
[x] Добавлены модели (`OrchestratorSettings`, `TestState`).
[x] Добавлен Redis repository `TestStateRepository`.
[x] Добавлен сервис мониторинга worker'ов (`WorkerMonitor`) как фоновой loop-заглушки.
[x] Собран bootstrap orchestrator (`build_app`, `run_orchestrator`) на `Robyn + redis.asyncio + uvloop`.
[x] Добавлены базовые маршруты API (`/health`, `/ready`).
[x] Добавлен CLI entrypoint `vikhry orchestrator start`.

## Наблюдения

1. `orchestrator stop` оставлен как заглушка до появления lifecycle manager процесса.
2. Детальная логика alive-worker detection будет добавлена в Step 3.
