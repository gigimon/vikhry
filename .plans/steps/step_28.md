# Step 28: Unified Outcome Metrics Contract

## Goal

Define a single outcome contract for all metric sources (lifecycle, step, HTTP, future clients) while preserving compatibility with the existing system.

## Implementation

[x] Expanded the runtime metrics contract with:
  - `source` (`lifecycle|step|http|jsonrpc|...`)
  - `stage` (`on_init|on_start|execute|...`)
  - `result_code`
  - `result_category` (`ok|protocol_error|transport_error|timeout|exception|...`)
  - `fatal`
  - `error_type`
  - `error_message`
[x] Implemented `result_code` normalization:
  - uppercase
  - whitelisted characters (`A-Z0-9_:-`)
  - length limit
  - fallback `UNKNOWN`
[x] Defined a low-cardinality policy:
  - `result_code` must not contain dynamic IDs, URL params, or full error texts
  - variable details go into a capped `error_message`
[x] Added unit tests for normalization and validation.

## Progress

- [x] Contract design approved
- [x] `result_code` normalization implemented
- [x] Contract tests added and passing
