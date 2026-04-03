# Step 45: Tests

## Goal

Cover the probe feature set with unit and integration tests across runtime, orchestrator, API, and worker behavior.

## Scope

- Unit tests for decorator, loader, and validation.
- Unit tests for worker probe runtime scheduling, timeout handling, and stop semantics.
- Unit tests for Redis read/write helpers and orchestrator probe service.
- Integration test with one probe-enabled worker and one normal worker.
- API tests for probe endpoints.

## Implementation

[x] Added unit tests for decorator, loader, and validation.
[x] Added unit tests for worker probe runtime scheduling, timeout handling, and stop semantics.
[x] Added unit tests for orchestrator probe service aggregation behavior.
[x] Added API tests for probe endpoints.
[ ] Add dedicated unit tests for Redis read/write helpers.
[ ] Add integration coverage for one probe-enabled worker and one normal worker.

## Verification

[x] Targeted backend unit suite passes for the implemented probe slices.
