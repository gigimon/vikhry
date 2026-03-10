# Step 35: CLI-команда `infra`

## Цель

Дать локальный операционный режим первого релиза: одной CLI-командой поднять Redis, orchestrator и несколько worker'ов для указанного сценария.

## Принятые решения

- Новый CLI namespace: `vikhry infra`.
- Минимальный API:
  - `vikhry infra up --worker-count N --scenario module.path:ClassName`
  - `vikhry infra down`
- Redis поднимается только через локальный Docker daemon.
- Используется выделенный container name и выделенный runtime-каталог внутри `DEFAULT_RUNTIME_DIR / "infra"`.
- `infra up` использует уже существующие detached-механизмы запуска orchestrator/worker.
- При любой ошибке старта выполняется best-effort cleanup уже поднятых процессов и Redis-контейнера.

## Реализация

[x] Добавить `infra_app` в Typer CLI.
[x] Выделить общие helper'ы запуска detached-процессов, чтобы ими могли пользоваться и текущие команды, и `infra`.
[x] Реализовать проверку Docker CLI и доступности daemon.
[x] Реализовать старт Redis-контейнера с фиксированным именем и ожиданием readiness через `PING`.
[x] Реализовать `infra up`:
  - orchestrator на `127.0.0.1:8080`;
  - Redis `redis://127.0.0.1:6379/0`;
  - worker id вида `infra-worker-<n>`;
  - pid/log files в `.../vikhry/infra/`.
[x] Реализовать `infra down` с остановкой worker'ов, orchestrator и удалением Redis-контейнера.
[x] Обновить README/CLI docs под новый режим запуска.

## Прогресс

- [x] `vikhry infra up --worker-count N --scenario ...` зарегистрирован в CLI.
- [x] Docker-check и readiness Redis добавлены.
- [x] Старт orchestrator/worker'ов переиспользует общий detached bootstrap.
- [x] Добавлен best-effort cleanup для error path и команда `vikhry infra down`.
- [x] README и `docs/0_cli.md` обновлены под новый режим.

## Риски и проверки

- Нужно явно отлавливать отсутствие `docker` и ошибку подключения к daemon.
- Нельзя перетирать уже запущенную инфраструктуру молча: нужны проверки pid/container state.
- Cleanup должен быть идемпотентным и безопасным при частично успешном старте.
