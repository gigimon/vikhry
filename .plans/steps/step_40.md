# Step 40: Probe event contract and Redis storage

## Goal

Define a dedicated probe event contract and keep probe storage fully separate from existing metrics streams.

## Scope

- Add worker Redis helpers for probe streams.
- Register probe names in `probes`.
- Append probe events to `probe:{name}`.
- Define the v1 event payload:
  - `name`
  - `worker_id`
  - `ts_ms`
  - `status`
  - `time`
  - `value`
  - optional `error_type`
  - optional `error_message`
- Keep probe storage fully separate from existing `metrics` / `metric:*` streams.

## Implementation

[x] Added worker Redis helpers for probe registration and event append.
[x] Registered probe names in the dedicated `probes` set.
[x] Stored probe events in dedicated `probe:{name}` streams.
[x] Standardized the probe event payload for v1.
[x] Kept probe streams separate from metrics streams.

## Verification

[x] Storage contract is exercised through worker runtime and orchestrator probe-service tests.
[ ] Dedicated unit tests for Redis helpers are still missing.
