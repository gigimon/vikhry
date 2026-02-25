# CLI утилита

## Основные задачи
1. Предоставлять единую точку для запуска всех компонентов системы (оркестратор, воркеры). Примерно так:
    ```bash
    vikhry orchestrator start --host 127.0.0.1 --port 8080 --redis-url redis://127.0.0.1:6379/0
    vikhry orchestrator stop
    vikhry worker start --redis-url redis://127.0.0.1:6379/0
    vikhry worker start --scenario my_load.scenarios:MyVU --http-base-url https://api.example.com
    vikhry worker stop
    ```
2. Предоставлять API для управления тестами, например:
    ```bash
    vikhry test start --users <number>
    vikhry test stop
    vikhry test change-users --users <number>
    ```
3. Не использовать конфигурационные файлы. Все runtime-параметры передаются только через аргументы командной строки.

## Алгоритм работы
Для своей работы использует пакет typer.

Запускает orchestrator и worker в detach-режиме по умолчанию.
Для foreground-запуска используется `--foreground`.

Поддерживается PID-based stop:
- `vikhry orchestrator stop --pid-file ... [--timeout-s ...] [--force]`
- `vikhry worker stop --pid-file ... [--timeout-s ...] [--force]`

Для работы с orchestrator api использует pyreqwest.

Значения по умолчанию (если нужны) задаются в CLI-опциях, а не во внешнем конфиге.

Worker runtime-опции сценария:
- `--scenario module.path:ClassName` — класс VU для запуска (default `vikhry.runtime.defaults:IdleVU`);
- `--http-base-url` — base URL для относительных HTTP шагов;
- `--vu-idle-sleep-s` — idle sleep интервал VU loop.

### Runtime файлы (`pid`, `log`)

По умолчанию используются пути:
- macOS: `~/Library/Caches/vikhry/`
- Linux: `$XDG_RUNTIME_DIR/vikhry/` или `/run/user/<uid>/vikhry/`, fallback `/tmp/vikhry/`
