# Алгоритм работы оркестратора

## Технологии

Используется асинхронная модель исполнения, в основе лежит uvloop для event loop и robyn для web части.  
Взаимодействие с Redis через `redis.asyncio`. Для JSON-команд используется `orjson`.

## Ограничения v1

1. Конфигурационный файл не используется, все параметры задаются через CLI.
2. Один сквозной run без `run_id`.
3. Один активный тест одновременно.
4. Нет `lifecycle lock` между несколькими orchestrator-инстансами.
5. Нет command acknowledgements (`ack/nack`).
6. Команды отправляются только в персональные каналы worker'ов (`worker:{worker_id}:commands`), без broadcast.

## Функциональность

- Инициализация: подключение к Redis, подготовка служебных ключей (`test:state`, `test:epoch`).
- Мониторинг worker'ов: периодическая проверка `worker:{worker_id}:status`.
- Управление тестом: `start_test`, `stop_test`, `change_users`.
- Распределение пользователей: round-robin по alive worker'ам.
- Работа с ресурсами: создание и учет ресурсов без автоматической очистки между запусками.
- Передача метрик в webui: чтение метрик из Redis и отдача через HTTP/WebSocket API.

## Состояния теста

Оркестратор работает по state machine:
`IDLE -> PREPARING -> RUNNING -> STOPPING -> IDLE`.

Правила:
1. `start_test` разрешен только из `IDLE`.
2. `change_users` разрешен только в `RUNNING`.
3. `stop_test` разрешен в `PREPARING` и `RUNNING`.

## Формат команд worker'ам

Команды сериализуются в JSON:

```json
{
  "type": "add_user",
  "command_id": "uuid",
  "epoch": 1,
  "sent_at": 1761571200,
  "payload": {
    "user_id": 10
  }
}
```

Поддерживаемые команды:
1. `start_test`
2. `stop_test`
3. `add_user`
4. `remove_user`

## Краткий алгоритм работы

1. При запуске orchestrator подключается к Redis и поднимает API на Robyn.
2. При `start_test`:
   - проверяет `test:state`; если не `IDLE`, возвращает ошибку;
   - ставит `test:state=PREPARING`, увеличивает `test:epoch`;
   - создает/дополняет ресурсы;
   - отправляет `start_test` каждому alive worker;
   - распределяет пользователей по worker'ам round-robin и отправляет серию `add_user`;
   - ставит `test:state=RUNNING`.
3. При `change_users`:
   - вычисляет дельту;
   - при увеличении шлет серию `add_user` с конкретными `user_id`;
   - при уменьшении шлет серию `remove_user`.
4. При `stop_test`:
   - ставит `test:state=STOPPING`;
   - отправляет `stop_test` каждому alive worker;
   - очищает пользовательские ключи;
   - не очищает ресурсы;
   - ставит `test:state=IDLE`.

### Примечание по согласованности с worker MVP

Worker в MVP переключает `epoch` только на `start_test`, поэтому orchestrator в `start_test`
сначала отправляет `start_test`, и только затем `add_user`.

## API эндпоинты (v1)

- `/create_resource` - создать ресурс(ы)
- `/start_test` - запуск теста с N users
- `/stop_test` - остановка теста
- `/change_users` - изменение целевого числа пользователей
- `/metrics` - получение метрик
- `/scenario/on_init_params` - параметры `on_init` из scenario-файла для UI

### `start_test` payload

`/start_test` принимает:
- `target_users` (обязательный)
- `init_params` (опциональный объект параметров для `VU.on_init`)
