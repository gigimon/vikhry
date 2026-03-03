# Step 31: UI tab Errors и tracebacks

## Цель

Добавить отдельный таб `Errors` для просмотра всех error events/tracebacks с фильтрацией по категории ошибок.

## Реализация

[x] Добавить новый таб `Errors` в навигацию UI.
[x] Реализовать выборку error events из `metrics.events` (источник `/metrics`).
[x] Добавить dropdown по `result_category` для фильтрации.
[x] Отображать traceback (или `error_message` как fallback), source/stage/metric и время события.
[x] Обновить API-клиент frontend для параметризованного `count` при запросе `/metrics`.
[x] Добавить описание таба `Errors` в `docs/5_ui.md`.

## Прогресс

- [x] Таб `Errors` добавлен.
- [x] Фильтрация по категории добавлена.
- [x] Отрисовка tracebacks реализована.
