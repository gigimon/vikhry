# Step 32: 1s RPS in UI and Topbar Synchronization

## Goal

Remove RPS mismatch between the statistics table and the topbar by switching to last-second RPS.

## Implementation

[x] Switched UI refresh frequency to 1 second (`REFRESH_INTERVAL_MS=1000`).
[x] Calculated frontend `RPS_1s` as the delta of `aggregate_total.requests` between adjacent ticks.
[x] Used `RPS_1s` in the statistics table regardless of `Window / Whole test` mode.
[x] Calculated topbar RPS as the sum of `RPS_1s` across all metrics except `source=step`.

## Progress

- [x] The table uses `RPS_1s`
- [x] The topbar excludes step metrics from total RPS
