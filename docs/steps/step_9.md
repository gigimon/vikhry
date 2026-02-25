# Step 9: CLI-интеграция

## Цель

Обновить CLI до v1-контракта:
- `Typer` как CLI framework;
- команды запуска/остановки orchestrator;
- команды управления тестом через HTTP orchestrator API;
- параметры runtime только через CLI-флаги;
- понятные операционные ошибки.

## Реализация

[x] CLI переведен на `Typer`:
  - группа `orchestrator`
  - группа `test`
[x] Реализованы команды orchestrator:
  - `vikhry orchestrator start`
  - `vikhry orchestrator stop`
[x] В `orchestrator start` добавлен `--scenario` (путь до Python-файла сценария),
   который передается в orchestrator runtime.
[x] Для `orchestrator stop` добавлен PID-based контроль процесса:
  - `--pid-file`
  - каскадный graceful stop (`SIGINT -> SIGTERM`)
  - опциональный `--force` (`SIGKILL`) и `--timeout-s`
[x] Для `orchestrator start` добавлен detach-режим по умолчанию:
  - background запуск с возвратом управления в терминал;
  - `--foreground` для блокирующего запуска;
  - `--log-file` и `--startup-timeout-s` для операционной диагностики.
[x] Дефолтные `pid/log` пути перенесены в системный runtime-каталог
    (macOS/Linux), вместо рабочей директории.
[x] Реализованы test-команды через HTTP к orchestrator:
  - `vikhry test start --users ...`
  - `vikhry test change-users --users ...`
  - `vikhry test stop`
[x] HTTP-клиент реализован через `pyreqwest` (`SyncClientBuilder`).
[x] Добавлены валидации и дружелюбные ошибки:
  - URL orchestrator
  - HTTP/network errors
  - invalid pid/stale pid file сценарии
[x] Все runtime-параметры orchestrator передаются через CLI-флаги.

## Наблюдения

1. `orchestrator stop` не зависит от API shutdown endpoint и работает через PID file.
2. Test-команды поддерживают `--orchestrator-url` и `--timeout-s` для операционной гибкости.
3. JSON-ответы orchestrator печатаются в CLI (pretty JSON) для диагностики.
