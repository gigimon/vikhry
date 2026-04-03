# Step 5: Lifecycle Manager (`start_test`, `change_users`, `stop_test`)

## Goal

Implement a strict fail-fast lifecycle manager for the state machine:
`IDLE -> PREPARING -> RUNNING -> STOPPING -> IDLE`

## Chosen Option

Option A: strict state guards with no implicit no-op transitions.

## Implementation

[x] Expanded `LifecycleService` with:
  - `start_test(target_users)`
  - `change_users(target_users)`
  - `stop_test()`
[x] Added strict transition errors:
  - `InvalidStateTransitionError(action, expected, current)`
[x] Implemented `start_test`:
  - atomic `IDLE -> PREPARING` plus `epoch++`;
  - orchestration of `add_user` and `start_test`;
  - transition of users to `running`;
  - transition to `RUNNING`;
  - rollback to `IDLE` and user cleanup on failure.
[x] Implemented `change_users` in `RUNNING` only:
  - compute the delta from the current user count;
  - scale up through `add_user`;
  - scale down through `remove_user`.
[x] Implemented `stop_test` from `PREPARING` and `RUNNING`:
  - transition to `STOPPING`;
  - send `stop_test` to alive workers;
  - clear user keys;
  - return to `IDLE`.
[x] Added bulk user-status update in the Redis repository (`set_all_users_status`).
[x] Integrated lifecycle management into orchestrator runtime.

## Notes

1. Resource preparation remained a placeholder in `_prepare_resources` until Step 6.
2. Scale-down uses deterministic removal order, with higher numeric `user_id` values removed first.
