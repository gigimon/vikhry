# Step 29: Runtime-эмиттеры и backend-агрегация ошибок

## Цель

Подключить unified outcome-контракт к источникам событий в runtime и агрегировать его в orchestrator `/metrics`.

## Реализация

[x] Lifecycle runtime:
  - при исключении в `on_init`/`on_start` отправлять failure-метрику с `source=lifecycle`, `stage=on_init|on_start`, `fatal=true`;
  - после такой ошибки не запускать step-цикл пользователя.
[x] Step runtime:
  - для успешного выполнения отправлять outcome (`result_code=STEP_OK`, `result_category=ok`);
  - для исключений отправлять (`result_code=STEP_EXCEPTION`, `result_category=exception`, `error_type`, `error_message`).
[x] HTTP runtime:
  - ответы: `result_code=HTTP_<status>`;
  - исключения: `result_code=HTTP_EXCEPTION`, `result_category=transport_error|timeout|exception`.
[x] Orchestrator MetricsService:
  - добавить агрегаты `result_code_counts`, `result_category_counts`, `fatal_count`;
  - ввести top-K коды + `OTHER` для ограничения кардинальности payload.
[x] Обновить контракт `/metrics` и документацию `docs/contracts/v1.md`.
[x] Добавить unit тесты на новую агрегацию и кейсы lifecycle/step/http ошибок.

## Прогресс

- [x] Runtime-эмиттеры обновлены.
- [x] Агрегатор `/metrics` расширен.
- [x] Тесты backend проходят.
