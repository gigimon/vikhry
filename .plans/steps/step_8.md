# Step 8: Metrics and Live Aggregation

## Goal

Add a live metrics flow with load control:
- read from `metric:{metric_id}` streams;
- provide lightweight aggregation for `RPS / latency / errors`;
- keep bounded in-memory state;
- track backlog, lag, and dropped updates for WebSocket subscribers.

## Implementation

[x] Reworked `MetricsService`:
  - background poller with `start/stop`;
  - incremental reads via `read_metric_events_after`;
  - rolling per-second aggregation with `window_s=60`;
  - bounded recent events per metric;
  - lag tracking when `max_events_per_metric_per_poll` is reached.
[x] Added backlog control for WebSocket fanout:
  - bounded queue per subscriber;
  - drop oldest on overflow;
  - `dropped_subscriber_messages` counter.
[x] Updated `/metrics`:
  - returns snapshot with `aggregate`, `lag`, and `events`;
  - supports `metric_id`, `count`, and `include_events`.
[x] Added WebSocket endpoint:
  - `GET ws /ws/metrics`
  - initial snapshot plus pushed `metrics_tick` updates
[x] Wired orchestrator runtime to start and stop `metrics_service`.

## `/metrics` Contract

The response includes:
1. `generated_at`
2. `lag`
   - `detected`
   - `metrics_with_backlog`
   - `dropped_subscriber_messages`
3. `metrics[]`
   - `metric_id`
   - `last_event_id`
   - `aggregate` (`window_s`, `requests`, `errors`, `error_rate`, `rps`, `latency_avg_ms`)
   - `events` when `include_events=true`
4. `count`
5. `include_events`

## Notes

1. Aggregation was intentionally lightweight at this stage: average latency only, without percentile support.
2. Backlog detection based on poll limits was considered sufficient for v1.
3. This step completed the WebSocket piece intentionally deferred in Step 7.
