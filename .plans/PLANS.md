# Description

`vikhry` is an async distributed load-testing framework designed for high concurrency, horizontal scaling, and scenarios that require globally unique shared resources. The system is built around Redis as the single coordination point, Python workers that execute virtual users, an orchestrator that manages lifecycle and aggregation, and a React UI for operational visibility.

The project covers:
- distributed load execution with multiple workers;
- virtual-user scenarios written in Python;
- global resource pooling and provisioning;
- orchestrated lifecycle (`IDLE -> PREPARING -> RUNNING -> STOPPING`);
- live metrics, error visibility, and probe-based observability;
- packaged UI, CLI automation, docs, and release workflows.

## Technologies

- Backend: Python 3.14, asyncio, Robyn, redis.asyncio, orjson, pyreqwest, Pydantic
- Frontend: React, TypeScript, Vite, Recharts
- Runtime and packaging: uvloop, uv, Hatch, wheel/sdist packaging
- Quality: pytest, ruff
- Operations: Docker, GitHub Actions, GHCR, PyPI
- Documentation: Astro Starlight

# Implementation

## Step 1 Orchestrator Process Skeleton
[x] Add orchestrator package structure, bootstrap, and graceful shutdown wiring
[x] Initialize Redis runtime state on startup
[x] Expose `/health` and `/ready`

## Step 2 Contracts and Redis Layer
[x] Add typed v1 command, worker, and user contracts
[x] Implement command serialization and deserialization
[x] Implement Redis repository for the full v1 keyspace
[x] Add atomic lifecycle primitives in Redis

## Step 3 Worker Presence Monitoring
[x] Implement alive-worker rules and cached worker presence service
[x] Add explicit failure path when no alive workers exist
[x] Expose alive worker information through `/ready`

## Step 4 User Orchestration and Commands
[x] Implement round-robin user allocation across alive workers
[x] Publish add/remove/start/stop commands to workers
[x] Persist user assignments and keep add/remove idempotent

## Step 5 Lifecycle Manager (`start_test`, `change_users`, `stop_test`)
[x] Add strict state-guarded lifecycle transitions
[x] Implement start, scale, stop, and rollback logic
[x] Keep user state cleanup and stop handling consistent

## Step 6 Resources and the Preparing Phase
[x] Add resource service with create and prepare flows
[x] Store resources in Redis using the defined key pattern
[x] Implement `POST /create_resource` with validation
[x] Delegate lifecycle preparation to the resource layer

## Step 7 Orchestrator HTTP API (Option C)
[x] Expose lifecycle, resource, and metrics flows through HTTP endpoints
[x] Add request models and validation for API inputs
[x] Normalize API error responses into a unified contract

## Step 8 Metrics and Live Aggregation
[x] Read metrics incrementally from Redis streams
[x] Build rolling aggregates and recent event snapshots
[x] Track backlog and dropped subscriber updates
[x] Expose live snapshots through `/metrics` and `/ws/metrics`

## Step 9 CLI Integration
[x] Add Typer-based orchestrator and test command groups
[x] Support detached process management for orchestrator
[x] Route test-control commands through the HTTP API
[x] Validate CLI inputs and surface actionable errors

## Step 10 v1 Testing and Stabilization
[x] Add unit coverage for contracts, orchestration, presence, and lifecycle
[x] Add integration coverage against real Redis
[x] Cover edge cases such as stale workers and rollback on failure
[ ] Add structured logging and internal orchestrator runtime metrics

## Step 11 Worker MVP Foundation (Control Plane)
[x] Add worker package and bootstrap
[x] Implement Redis registration and heartbeat
[x] Implement sequential command loop for lifecycle and user operations
[x] Expose worker lifecycle through CLI commands

## Step 18 Worker MVP Testing and Documentation
[x] Add worker dispatcher and heartbeat unit tests
[x] Add Redis-backed integration tests
[x] Cover end-to-end orchestrator plus worker smoke flow
[x] Update worker-related documentation

## Step 19 API Contracts for UI
[x] Add stable `/workers` endpoint for frontend snapshots
[x] Add stable `/resources` endpoint for frontend snapshots
[x] Update API contract documentation
[x] Cover new endpoints with unit and integration tests

## Step 20 Metrics Expansion (Exact Percentiles)
[x] Add median, p95, and p99 latency aggregation
[x] Preserve backward compatibility of older aggregate fields
[x] Return `null` for empty latency windows
[x] Cover percentile edge cases with tests

## Step 28 Unified Outcome Metrics Contract
[x] Add normalized outcome fields to runtime metrics
[x] Implement `result_code` normalization
[x] Define low-cardinality rules for outcome reporting
[x] Cover the new contract with validation tests

## Step 29 Runtime Emitters and Backend Error Aggregation
[x] Emit normalized lifecycle, step, and HTTP outcomes
[x] Aggregate result codes, categories, and fatal counts in `/metrics`
[x] Update backend docs for the expanded metrics contract
[x] Cover new aggregation paths with backend tests

## Step 30 UI Breakdown and Operational Visibility
[ ] Add frontend types for the expanded `/metrics` aggregates
[ ] Render breakdown panels in the statistics tab
[ ] Add filtering and grouping by metric source
[ ] Add frontend tests and docs for the breakdown UI

## Step 31 UI `Errors` Tab and Tracebacks
[x] Add `Errors` tab to frontend navigation
[x] Extract error events from `/metrics`
[x] Add category filtering for error browsing
[x] Render tracebacks and error metadata in the UI

## Step 32 1s RPS in UI and Topbar Synchronization
[x] Refresh the UI on a 1-second cadence
[x] Use per-second deltas for table RPS
[x] Use the same basis for topbar RPS
[x] Exclude step metrics from total topbar RPS

## Step 33 Charts UX Overhaul
[x] Unify chart controls around dropdown-based UX
[x] Support chart series selection for RPS and latency
[x] Add time-range selection for charts
[x] Visualize user-count change points

## Step 34 Embedding UI into the Python Package
[x] Include built UI assets in wheel and sdist
[x] Serve packaged static assets and SPA fallback from orchestrator
[x] Fail packaging clearly when assets are missing
[x] Document packaged UI behavior

## Step 35 `infra` CLI Command
[x] Add `vikhry infra up` and `vikhry infra down`
[x] Manage Redis through Docker with readiness checks
[x] Reuse detached orchestrator and worker startup
[x] Keep cleanup safe and best-effort on failures

## Step 36 GitHub Actions for Release Automation
[x] Build frontend and Python artifacts in GitHub Actions
[x] Add PyPI publish path
[x] Build and publish runtime Docker image to GHCR
[x] Document release automation

## Step 37 Public Documentation
[x] Create docs app in `docs/`
[x] Add initial documentation sections for introduction, run flow, and scenarios
[x] Keep docs build and checks passing
[ ] Finish GitHub Pages publishing

## Step 38 Probe DSL and Scenario Loading
[x] Add `@probe(...)` decorator to the runtime DSL
[x] Implement probe metadata and validation
[x] Enforce module-level async-only probe targets
[x] Discover declared probes from scenarios

## Step 39 Worker-Side Probe Runtime
[x] Add dedicated probe runtime on workers
[x] Start probe runtime only with `--run-probes`
[x] Schedule probes independently with timeout handling
[x] Keep probe failures isolated from VU execution

## Step 40 Probe Event Contract and Redis Storage
[x] Register probe names in `probes`
[x] Append probe events to `probe:{name}`
[x] Standardize probe event payload fields
[ ] Add dedicated Redis-helper unit tests

## Step 41 Orchestrator Probe Read Path
[x] Read probe streams from orchestrator
[x] Add dedicated `ProbeService`
[x] Aggregate latest value, counters, and recent history
[ ] Add dedicated Redis-helper unit tests

## Step 42 API and CLI Integration
[x] Expose `--run-probes` in worker CLI
[x] Wire probe startup through the worker app
[x] Add `/probes` and `/probes/history`
[x] Keep probe API separate from `/metrics`

## Step 43 UI Support
[x] Add frontend types and API calls for probes
[x] Render one chart per probe
[x] Expose probes as a dedicated tab in the UI
[x] Handle empty and error states cleanly

## Step 44 Documentation and Examples
[x] Document probe usage and `--run-probes` in example docs
[x] Add probe usage to the example scenario
[ ] Expand the example to multiple probes
[ ] Add explicit guidance about running probes on only one chosen worker

## Step 45 Tests
[x] Add unit tests for probe DSL and worker runtime behavior
[x] Add probe-service tests
[x] Add probe endpoint tests
[ ] Add dedicated Redis-helper tests
[ ] Add mixed-worker integration coverage
