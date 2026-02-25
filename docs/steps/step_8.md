# Step 8: Метрики и live-агрегация

## Цель

Добавить поток live-метрик с контролем нагрузки:
- чтение из `metric:{metric_id}` streams;
- минимальная агрегация `RPS / latency / errors`;
- bounded in-memory хранение;
- контроль backlog/lag и dropped updates для WebSocket подписчиков.

## Реализация

[x] Переписан `MetricsService`:
  - фоновый poller (`start/stop`);
  - чтение новых событий по cursor (`read_metric_events_after`);
  - rolling window агрегация (по секундам, `window_s=60` по умолчанию);
  - bounded recent events per metric;
  - lag tracking при достижении `max_events_per_metric_per_poll`.
[x] Добавлен backlog control для WebSocket fanout:
  - bounded queue per subscriber;
  - drop oldest при переполнении;
  - счетчик `dropped_subscriber_messages`.
[x] API `/metrics` обновлен:
  - возвращает snapshot с `aggregate`, `lag`, `events`;
  - поддерживает `metric_id`, `count`, `include_events`.
[x] Добавлен WebSocket endpoint:
  - `GET ws /ws/metrics`;
  - initial snapshot + push тиков `metrics_tick`.
[x] Orchestrator runtime:
  - запускает `metrics_service` на startup;
  - останавливает на shutdown.

## Контракт ответа `/metrics`

Ответ включает:
1. `generated_at` — unix timestamp.
2. `lag`:
   - `detected`
   - `metrics_with_backlog`
   - `dropped_subscriber_messages`
3. `metrics[]`:
   - `metric_id`
   - `last_event_id`
   - `aggregate` (`window_s`, `requests`, `errors`, `error_rate`, `rps`, `latency_avg_ms`)
   - `events` (если `include_events=true`)
4. `count`, `include_events`.

## Наблюдения

1. Аггрегация intentionally lightweight: без p95/p99, только average latency.
2. Backlog определяется по достижению poll limit, что достаточно для v1 защиты от перегрузки.
3. Step 7 WebSocket-пункт закрыт здесь по выбранному пути Option C -> Step 8.

