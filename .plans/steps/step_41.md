# Step 41: Orchestrator probe read path

## Goal

Add an orchestrator-side read path for probes that is fully separate from the existing metrics aggregation flow.

## Scope

- Add orchestrator Redis helpers to list probes and read `probe:{name}` streams.
- Add a dedicated orchestrator service for probes, separate from `MetricsService`.
- Implement aggregation for probes:
  - latest value
  - last event id
  - success/error counters in current window
  - recent events history
- Reset probe in-memory state together with a new test run.

## Implementation

[x] Added orchestrator Redis helpers for probe streams.
[x] Added a dedicated `ProbeService`.
[x] Implemented latest value and last event id tracking.
[x] Implemented success/error counters for the rolling window.
[x] Implemented recent events history.
[x] Reset probe in-memory state on a new test run.

## Verification

[x] Unit coverage added for orchestrator probe aggregation behavior.
[ ] Dedicated unit tests for Redis helpers are still missing.
