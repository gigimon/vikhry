# Step 28: Унифицированный контракт outcome-метрик

## Цель

Сформировать единый контракт исходов выполнения для всех типов метрик (lifecycle/step/http/будущие клиенты), сохранив текущую совместимость.

## Реализация

[x] Расширить runtime metrics contract полями:
  - `source` (`lifecycle|step|http|jsonrpc|...`);
  - `stage` (`on_init|on_start|execute|...`);
  - `result_code` (нормализованная строка);
  - `result_category` (`ok|protocol_error|transport_error|timeout|exception|...`);
  - `fatal` (bool);
  - `error_type` (класс исключения, если есть);
  - `error_message` (краткая строка ограниченной длины).
[x] Реализовать helper нормализации `result_code`:
  - uppercase;
  - whitelist символов (`A-Z0-9_:-`);
  - ограничение длины (например, 64);
  - fallback `UNKNOWN`.
[x] Зафиксировать policy low-cardinality:
  - `result_code` не должен включать динамические id/url params/полные тексты ошибок;
  - вариативные детали хранятся в `error_message`, но с ограничением длины.
[x] Добавить unit-тесты на нормализацию/валидацию.

## Прогресс

- [x] Дизайн контракта утвержден.
- [x] Нормализация `result_code` реализована.
- [x] Тесты контракта добавлены и проходят.
