# Алгоритм работы worker (v1)

## Что реализовано сейчас

Worker реализует control-plane и runtime VU:
- регистрация в `workers`;
- heartbeat в `worker:{worker_id}:status`;
- подписка на `worker:{worker_id}:commands`;
- последовательная обработка `start_test/stop_test/add_user/remove_user`;
- локальное состояние (`phase`, `current_epoch`, `assigned_users`, `user_tasks`);
- запуск VU-задач по `add_user` и остановка по `remove_user`/`stop_test`;
- публикация step-событий в `metric:worker:{worker_id}`;
- CLI управление процессом (`start/stop`, detach/foreground).

## Настройка сценария

Worker загружает VU-класс по import path `module.path:ClassName`:
- `--scenario` (по умолчанию: `vikhry.runtime.defaults:IdleVU`);
- `--http-base-url` для относительных HTTP путей в сценарии;
- `--vu-idle-sleep-s` для idle-паузы, когда нет eligible step.

## Технологии

- asyncio + uvloop
- redis.asyncio
- orjson (через общий `CommandEnvelope`)
- Typer (CLI запуск/остановка)

## Healthcheck

Worker обновляет hash:
- `worker:{worker_id}:status`
- поля:
  - `status`: `healthy | unhealthy`
  - `last_heartbeat`: unix timestamp
  - `cpu_percent`: загрузка процесса worker (проценты)
  - `rss_bytes`: потребление памяти процесса worker (RSS, bytes)
  - `memory_percent`: доля RSS от системной памяти (проценты)

На graceful shutdown worker делает best-effort `status=unhealthy`, затем unregister.

## Worker ID

- По умолчанию генерируется автоматически (`uuid4().hex[:8]`).
- Можно задать явно через `--worker-id`.
- Один выбранный `worker_id` используется во всех Redis-ключах процесса.

## Формат входящих команд

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
1. `start_test`
2. `stop_test`
3. `add_user`
4. `remove_user`

## Правила обработки команд (v1 MVP)

1. Команды обрабатываются строго по одной (single-threaded dispatcher).
2. Невалидный JSON и неизвестный `type` игнорируются с логом.
3. `ack/nack` отсутствуют.
4. `epoch`-правила:
   - `start_test` с большим `epoch` переключает worker на этот `epoch`;
   - `start_test` со старым `epoch` игнорируется;
   - `add_user/remove_user/stop_test` принимаются только если `command.epoch == current_epoch`.
5. Идемпотентность:
   - повторный `add_user` не дублирует локальное назначение;
   - повторный `remove_user` безопасен;
   - повторный `start_test`/`stop_test` не ломает состояние.

## Локальный lifecycle worker

- начальное состояние: `IDLE`, `current_epoch=0`, `assigned_users=∅`;
- `start_test`: переход в `RUNNING` и переключение epoch;
- `add_user`: добавляет `user_id` в локальный набор и поднимает task с VU loop;
- `remove_user`: удаляет `user_id` из локального набора и останавливает его VU task;
- `stop_test`: `STOPPING -> IDLE`, очистка локального состояния.

## Логи worker

Worker пишет логи о:
- запуске процесса (`startup initiated`);
- успешном/неуспешном подключении к Redis;
- старте подписки на командный канал;
- получении каждой команды (`command_id`, `type`, `epoch`);
- остановке процесса.

## CLI

Примеры:

```bash
vikhry worker start --redis-url redis://127.0.0.1:6379/0
vikhry worker start --foreground --worker-id w1
vikhry worker start --scenario my_load.scenarios:MyVU --http-base-url https://api.example.com
vikhry worker stop --pid-file /path/to/worker.pid
```

По умолчанию используется detach-режим и runtime-файлы (`pid/log`) в системном runtime-каталоге.
