# Changelog

## 0.1.2 - 2026-03-11

### Added

- Added `JsonRPCClient` as a lazy runtime client for VU scenarios with `call(...)` support.
- Added JSON-RPC protocol handling with request validation, response parsing, and dedicated exceptions.
- Added unit coverage for JSON-RPC request construction, error handling, and runtime instrumentation.

### Changed

- Extended runtime client resolution to support both `request()`-based HTTP clients and `call()`-based JSON-RPC clients.
- Added JSON-RPC metrics emission with `source=jsonrpc` and normalized `result_code` values.
