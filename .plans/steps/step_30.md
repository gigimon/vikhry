# Step 30: UI Breakdown and Operational Visibility

## Goal

Add transparent UI diagnostics for execution outcomes based on `result_code`, `result_category`, and `fatal`.

## Implementation

[ ] Add frontend API typings for the new `/metrics` aggregate fields:
  - `result_code_counts`
  - `result_category_counts`
  - `fatal_count`
  - `top_result_codes` plus `OTHER`
[ ] Add a breakdown block to the statistics tab:
  - top result codes
  - category distribution
  - dedicated fatal lifecycle indicator
[ ] Add filtering and grouping by `source` (`lifecycle`, `step`, `http`, ...)
[ ] Ensure stable UX at scale:
  - top-K plus `OTHER`
  - limit the number of displayed rows
  - sort by descending frequency
[ ] Add frontend formatting and rendering tests plus smoke checks
[ ] Update `docs/5_ui.md`

## Progress

- [ ] Frontend types updated
- [ ] UI breakdown implemented
- [ ] Frontend tests passing
