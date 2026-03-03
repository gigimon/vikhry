# Основные компоненты системы

1. Оркестратор - центральный компонент, который общается с Redis, управляет worker'ами и предоставляет API для CLI/UI.
2. Worker - отдельный процесс, который выполняет VU, исполняет команды оркестратора и пишет метрики.
3. Redis - единая точка координации состояния, команд и метрик.

# Ограничения v1

1. Один сквозной run, без `run_id`.
2. Только один активный тест в системе.
3. `lifecycle lock` между несколькими orchestrator-инстансами не делается (операционная ответственность пользователя).
4. Управляющие команды worker'ам идут через Redis Pub/Sub.
5. Подтверждения команд (`ack/nack`) не используются.
6. Broadcast-канал не используется: оркестратор отправляет команды в персональный канал каждого worker.
7. Масштабирование пользователей только через `add_user`/`remove_user`.
8. Распределение пользователей между worker'ами - `round-robin`.

# Структуры данных в Redis

1. Состояние теста
   - `test:state` - string: `IDLE | PREPARING | RUNNING | STOPPING`
   - `test:epoch` - integer, увеличивается при каждом `start_test`
2. Пользователи
   - `users` - set со всеми активными `user_id`
   - `user:{user_id}` - hash: `status` (`pending | running`), `worker_id`, `updated_at`
3. Ресурсы
   - `resources` - hash, где ключ это имя ресурса, значение - количество
   - `resource:{resource_name}:{id}` - json со всеми данными ресурса
   - дубли ресурсов в v1 допустимы
4. Worker'ы
   - `workers` - set всех `worker_id`
   - `worker:{worker_id}:commands` - pub/sub канал команд для конкретного worker
   - `worker:{worker_id}:users` - set назначенных пользователи для worker
   - `worker:{worker_id}:active_users` - set пользователей, которые прошли `on_init/on_start` и реально выполняются
   - `worker:{worker_id}:status` - hash healthcheck: `status` (`healthy | unhealthy`), `last_heartbeat`
5. Метрики
   - `metrics` - set названий метрик
   - `metric:{metric_id}` - stream сырых событий метрик

# Формат управляющих команд (JSON)

Команда публикуется в `worker:{worker_id}:commands`:

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

Поддерживаемые `type`:
1. `start_test` (`payload`: `target_users`)
2. `stop_test` (`payload`: пустой объект)
3. `add_user` (`payload`: `user_id`)
4. `remove_user` (`payload`: `user_id`)

# Схема работы

## Инициализация компонентов
1. Оркестратор подключается к Redis и инициализирует ключи состояния теста.
2. Worker стартует, добавляет `worker_id` в `workers`, подписывается на `worker:{worker_id}:commands`.
3. Worker обновляет `worker:{worker_id}:status` в heartbeat loop.
4. Оркестратор периодически читает `worker:{worker_id}:status` и определяет активных worker по `last_heartbeat`.

## Запуск теста
1. Оркестратор принимает `start_test`.
2. Если `test:state != IDLE`, возвращается ошибка.
3. Оркестратор переводит тест в `PREPARING`, увеличивает `test:epoch`.
4. Создает/дополняет ресурсы (без обязательной очистки перед новым запуском).
5. Распределяет пользователей по alive worker по алгоритму `round-robin`.
6. Для каждого пользователя отправляет JSON-команду `add_user` в канал выбранного worker.
7. После отправки назначений отправляет `start_test` в канал каждого alive worker.
8. Переводит `test:state` в `RUNNING`.

## Изменение количества пользователей
1. Работает только при `test:state == RUNNING`.
2. Увеличение - серия команд `add_user` с конкретными `user_id`.
3. Уменьшение - серия команд `remove_user` с конкретными `user_id`.
4. Подтверждения выполнения команд в v1 не используются.

## Остановка теста
1. Оркестратор переводит тест в `STOPPING`.
2. Отправляет `stop_test` каждому alive worker в его персональный канал.
3. Очищает данные пользователей (`users`, `user:*`, `worker:*:users`, `worker:*:active_users`).
4. Ресурсы не удаляются автоматически.
5. Переводит `test:state` в `IDLE`.
