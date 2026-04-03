# Step 7: Orchestrator HTTP API (Option C)

## Goal

Implement the v1 HTTP API over the service layer:
- `/start_test`
- `/stop_test`
- `/change_users`
- `/create_resource`
- `/metrics`

The chosen scope includes a unified error format and explicitly defers WebSocket support to the next step.

## Chosen Option

Option C: HTTP first, WebSocket later.

## Implementation

[x] Added API request models:
  - `StartTestRequest`
  - `ChangeUsersRequest`
[x] Added `MetricsService` for HTTP metric reads.
[x] Added HTTP endpoints:
  - `POST /start_test`
  - `POST /change_users`
  - `POST /stop_test`
  - `POST /create_resource`
  - `GET /metrics`
[x] Added a unified error format:
  - `invalid_json`
  - `validation_error`
  - `invalid_state`
  - `no_alive_workers`
  - `bad_request`
  - `internal_error`
[x] Added payload aliases:
  - `users -> target_users` for `/start_test` and `/change_users`

## Notes

1. `health` and `ready` were already in place, so no extra work was needed there.
2. The WebSocket metric stream was intentionally postponed.
3. `/metrics` still returned raw stream events at this stage; aggregation came next.
