# Step 44: Documentation and examples

## Goal

Document probe usage and show it in the example scenario.

## Scope

- Document probe DSL and worker flag `--run-probes`.
- Add example scenario module with multiple probes.
- Explain the operational recommendation: enable probes only on one chosen worker unless duplication is desired.

## Implementation

[x] Documented probe usage and `--run-probes` in the example README.
[x] Added a probe usage example to the existing example scenario.
[ ] Expand the example into multiple probes.
[ ] Add explicit operational guidance about running probes on only one chosen worker unless duplication is desired.

## Verification

[x] Example scenario compiles and passes `ruff check`.
