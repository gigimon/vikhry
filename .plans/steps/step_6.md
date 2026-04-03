# Step 6: Resources and the Preparing Phase

## Goal

Implement the base orchestrator-side resource layer for v1:
- resource preparation during `PREPARING` via a dedicated service;
- writes into `resources` and `resource:{resource_name}:{id}`;
- preserve the v1 policy of allowing duplicates and not auto-cleaning;
- expose `POST /create_resource` with validation.

## Chosen Option

Option A: a simple orchestrator-side resource service without a distributed provisioning job pipeline.

## Implementation

[x] Added Pydantic resource models:
  - `CreateResourceRequest`
  - `CreateResourceResult`
[x] Implemented `ResourceService`:
  - `create_resources(resource_name, count, payload)`
  - `prepare_for_start(target_users)`
  - `counters()`
[x] Implemented `create_resources` writes:
  - resource counters via `HINCRBY` in `resources`
  - resource payloads in `resource:{resource_name}:{id}`
[x] Integrated lifecycle with the preparing phase:
  - `LifecycleService._prepare_resources()` delegates to `ResourceService.prepare_for_start()`
[x] Added endpoint:
  - `POST /create_resource` with request validation and `400` JSON errors
[x] Preserved v1 policy:
  - no automatic cleanup on `stop_test`
  - no deduplication

## Notes

1. Auto-preparation in `PREPARING` supports on-demand resource creation based on scenario declarations and target user count.
2. `/create_resource` also allows manual pool prefill.
