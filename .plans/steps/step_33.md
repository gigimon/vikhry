# Step 33: Charts UX Overhaul

## Goal

Make the `Charts` tab operationally useful with unified dropdown controls, correct series selection, time ranges, and user-change visualization.

## Implementation

[x] Moved chart controls to a unified dropdown pattern on the right side.
[x] Updated `Requests Per Second`:
  - metric dropdown ordered as `step -> http -> other`
  - separate dropdown for the `Users` series
  - visual markers for user-count change points
[x] Added a `5 / 15 / 30 minutes / All time` range selector for both charts, defaulting to `All time`.
[x] Updated `Latency`:
  - dropdown for metric selection
  - dropdown for latency type (`average|median|p95|p99`)
[x] Kept chart history for the full run and filtered it by the selected range.

## Progress

- [x] Chart UX unified through dropdowns
- [x] Series and metric selection implemented for both charts
- [x] Time ranges and user-change markers working
