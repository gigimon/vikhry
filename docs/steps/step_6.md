# Step 6: Ресурсы и подготовительная фаза

## Цель

Реализовать базовый orchestrator-side ресурсный слой v1:
- подготовка ресурсов в `PREPARING` через выделенный сервис;
- запись ресурсов в `resources` и `resource:{resource_name}:{id}`;
- сохранение политики v1 (дубли допустимы, автоочистки нет);
- API `POST /create_resource` с валидацией.

## Выбранный вариант

Option A: простой сервис ресурсов в orchestrator без распределенного provisioning job pipeline.

## Реализация

[x] Добавлены pydantic модели ресурсов:
  - `CreateResourceRequest`
  - `CreateResourceResult`
[x] Реализован `ResourceService`:
  - `create_resources(resource_name, count, payload)`
  - `prepare_for_start(target_users)`
  - `counters()`
[x] `create_resources` пишет:
  - счетчик в `resources` через `HINCRBY`
  - данные ресурса в `resource:{resource_name}:{id}`
[x] Lifecycle интегрирован с подготовительной фазой:
  - `LifecycleService._prepare_resources()` делегирует в `ResourceService.prepare_for_start()`.
[x] Добавлен endpoint:
  - `POST /create_resource` (валидация входа, JSON-ошибки `400`).
[x] Политика v1 соблюдена:
  - ресурсы не очищаются автоматически на `stop_test`;
  - dedup не выполняется.

## Наблюдения

1. `default_prepare_counts` сейчас пустой, поэтому автоматическое создание в `PREPARING`
   не включено до появления DSL/конфигурации сценария.
2. API `/create_resource` уже позволяет наполнять глобальный пул вручную.

