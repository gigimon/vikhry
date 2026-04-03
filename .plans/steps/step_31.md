# Step 31: UI `Errors` Tab and Tracebacks

## Goal

Add a dedicated `Errors` tab for browsing error events and tracebacks with category-based filtering.

## Implementation

[x] Added the `Errors` tab to UI navigation.
[x] Implemented error-event extraction from `metrics.events` returned by `/metrics`.
[x] Added a dropdown filter by `result_category`.
[x] Rendered traceback content, with `error_message` as a fallback, together with source, stage, metric, and event time.
[x] Updated the frontend API client to support a parameterized `count` for `/metrics`.
[x] Added documentation for the `Errors` tab in `docs/5_ui.md`.

## Progress

- [x] `Errors` tab added
- [x] Category filtering added
- [x] Traceback rendering implemented
