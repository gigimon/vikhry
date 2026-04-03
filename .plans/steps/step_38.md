# Step 38: Probe DSL and scenario loading

## Goal

Introduce the runtime DSL primitives needed to declare probes inside scenario modules and discover them from orchestrator-side scenario loading.

## Scope

- Add a new module-level decorator `@probe(name=..., every_s=..., timeout=...)`.
- Add probe metadata model (`ProbeSpec`) and loader utilities similar to `resource`.
- Add validation rules:
  - `name` must be unique and non-empty.
  - `every_s` must resolve to `> 0`.
  - `timeout` must be `> 0` when provided.
  - probe targets must be async module-level callables.
- Export `probe` from public runtime package.

## Implementation

[x] Added `ProbeSpec` to runtime DSL metadata.
[x] Added module-level decorator `@probe(...)`.
[x] Added validation for `name`, `every_s`, and `timeout`.
[x] Restricted probe targets to async module-level callables.
[x] Added probe collection helpers for scenario modules.
[x] Exported `probe` and `ProbeSpec` from the public runtime package.
[x] Extended orchestrator scenario loading to read declared probe names.

## Verification

[x] Unit coverage added for decorator, loader, and validation behavior.
