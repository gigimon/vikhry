# Step 4: User Orchestration and Commands

## Goal

Implement the orchestration layer that:
- assigns users to workers;
- publishes commands to workers;
- guarantees idempotent `add/remove` behavior;
- uses stateless round-robin allocation (Option B).

## Chosen Option

Option B: recompute allocation on every request from the current alive-worker snapshot.

## Implementation

[x] Added allocator `allocate_round_robin(user_ids, worker_ids)`:
  - deterministic ordering by input worker list;
  - no global cursor.
[x] Added `UserOrchestrationService`:
  - `add_users(...)` publishes `add_user` and writes assignments;
  - `remove_users(...)` publishes `remove_user` and clears assignments;
  - `send_start_test(...)` publishes `start_test` to all alive workers;
  - `send_stop_test(...)` publishes `stop_test` to all alive workers.
[x] Implemented idempotency:
  - repeated `add` for an existing `user_id` is skipped;
  - repeated `remove` for a missing `user_id` is skipped.
[x] Integrated the service into the orchestrator runtime for later lifecycle steps.

## Notes

1. Option B is simpler and does not require a persistent Redis cursor.
2. Some imbalance across multiple calls is acceptable for this strategy.
