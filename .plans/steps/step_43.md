# Step 43: UI support

## Goal

Expose probes in the frontend as observability signals, separate from load metrics.

## Scope

- Add a dedicated UI section/tab for probes instead of mixing them into step statistics.
- Show latest probe values, update time, status, and short history.
- Make it visually clear that probes are observability signals, not load metrics.
- Handle the case when no worker runs probes.

## Implementation

[x] Added dedicated frontend API typings and client calls for probes.
[x] Added probe charts UI with one chart per probe.
[x] Moved the probe view into a dedicated `Probes` tab inside the main dashboard.
[x] Showed latest value, status, update time, counters, and recent chart history.
[x] Added empty/error states when no probe-enabled worker is producing data.
[x] Kept the visual treatment separate from step statistics and charts.

## Verification

[x] Frontend build and lint pass with the probe tab enabled.
