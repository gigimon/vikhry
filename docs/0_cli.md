# CLI утилита

## Основные задачи
1. Предоставлять единую точку для запуска всех компонентов системы (оркестратор, воркеры). Примерно так:
    ```bash
    vikhry orchestrator start --redis-host <host> --redis-port <port> --redis-password <password> --redis-db <db> --webui-host <host> --webui-port <port> --test-file <path>
    vikhry orchestrator stop
    vikhry worker start --redis-host <host> --redis-port <port> --redis-password <password> --redis-db <db> --test-file <path>
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

Запускает оркестратор и воркер, не привязывается к ним (делает detach)

Для работы с orchestrator api использует pyreqwest.

Значения по умолчанию (если нужны) задаются в CLI-опциях, а не во внешнем конфиге.
