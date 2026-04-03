# Changelog

## 0.2.0 - 2026-04-03

### Added

- Added module-level probes via `@probe(...)`, worker-side probe execution with `--run-probes`, and orchestrator/API support for probe streams and recent history.
- Added probe charts to the frontend as a dedicated `Probes` tab with one chart per probe and live refresh.
- Added probe usage to the example scenario and documented how to run probe-enabled workers.

## 0.1.2 - 2026-03-11

### Added

- Added `JsonRPCClient` as a lazy runtime client for VU scenarios with `call(...)` support.
- Added JSON-RPC protocol handling with request validation, response parsing, and dedicated exceptions.
- Added unit coverage for JSON-RPC request construction, error handling, and runtime instrumentation.

### Changed

- Extended runtime client resolution to support both `request()`-based HTTP clients and `call()`-based JSON-RPC clients.
- Added JSON-RPC metrics emission with `source=jsonrpc` and normalized `result_code` values.
