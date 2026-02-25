# Step 5: Lifecycle manager (`start_test`, `change_users`, `stop_test`)

## Цель

Реализовать строгий (fail-fast) lifecycle manager по state machine:
`IDLE -> PREPARING -> RUNNING -> STOPPING -> IDLE`.

## Выбранный вариант

Option A: строгий state guard без неявных no-op переходов.

## Реализация

[x] Расширен `LifecycleService`:
  - `start_test(target_users)`
  - `change_users(target_users)`
  - `stop_test()`
[x] Добавлены строгие ошибки переходов:
  - `InvalidStateTransitionError(action, expected, current)`.
[x] `start_test`:
  - атомарный переход `IDLE -> PREPARING` + `epoch++`;
  - оркестрация `add_user` и `start_test`;
  - перевод пользователей в `running`;
  - переход в `RUNNING`;
  - rollback в `IDLE` + очистка пользователей при ошибке.
[x] `change_users` (только в `RUNNING`):
  - вычисление дельты от текущего числа пользователей;
  - увеличение через `add_user`;
  - уменьшение через `remove_user`.
[x] `stop_test` (только из `PREPARING`/`RUNNING`):
  - переход в `STOPPING`;
  - отправка `stop_test` alive worker'ам;
  - очистка пользовательских ключей;
  - возврат в `IDLE`.
[x] Добавлена операция массового обновления пользовательского статуса в Redis repository (`set_all_users_status`).
[x] Lifecycle интегрирован в runtime orchestrator.

## Наблюдения

1. Подготовка ресурсов пока заглушена в `_prepare_resources` и будет реализована в Step 6.
2. В `change_users` для уменьшения используется детерминированный порядок удаления
   (высшие `user_id` сначала для числовых идентификаторов).

