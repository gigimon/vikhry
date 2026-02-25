# Step 4: Оркестрация пользователей и команд

## Цель

Реализовать слой оркестрации, который:
- назначает пользователей на worker'ы;
- публикует команды worker'ам;
- поддерживает идемпотентность `add/remove` операций;
- работает в режиме stateless round-robin (Option B).

## Выбранный вариант

Option B: распределение пользователей рассчитывается заново на каждый запрос
на основе актуального snapshot alive worker'ов.

## Реализация

[x] Добавлен allocator `allocate_round_robin(user_ids, worker_ids)`:
  - детерминированный порядок по входному списку worker'ов;
  - без глобального курсора.
[x] Добавлен `UserOrchestrationService`:
  - `add_users(...)` -> publish `add_user` + запись assignment;
  - `remove_users(...)` -> publish `remove_user` + очистка assignment;
  - `send_start_test(...)` -> publish `start_test` всем alive worker'ам;
  - `send_stop_test(...)` -> publish `stop_test` всем alive worker'ам.
[x] Реализована идемпотентность:
  - повторный `add` для существующего `user_id` пропускается;
  - повторный `remove` для отсутствующего `user_id` пропускается.
[x] Сервис интегрирован в runtime orchestrator для использования в следующих шагах.

## Наблюдения

1. Вариант B проще и не требует отдельного курсора в Redis.
2. Потенциальный перекос распределения между несколькими вызовами допустим
   в рамках выбранного варианта.

