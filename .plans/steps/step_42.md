# Step 42: API and CLI integration

## Goal

Expose probe functionality through worker CLI wiring and dedicated orchestrator API endpoints.

## Scope

- Add worker CLI flag `--run-probes`.
- Thread this flag through worker app startup and runtime wiring.
- Add dedicated orchestrator endpoint(s):
  - `GET /probes`
  - optional `GET /probes/history`
- Keep probe API separate from `/metrics`.

## Implementation

[x] Added worker CLI flag `--run-probes`.
[x] Threaded the flag through worker startup and runtime wiring.
[x] Added `GET /probes`.
[x] Added `GET /probes/history`.
[x] Kept probe API separate from `/metrics`.

## Verification

[x] Unit coverage added for CLI flag wiring.
[x] API coverage added for probe endpoints.
