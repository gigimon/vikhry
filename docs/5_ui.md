# UI

## Stack

The UI is built with:
- React
- TypeScript
- Vite
- Recharts

The frontend is bundled into the Python package and served by the orchestrator.

## Main layout

The UI is organized around:
- a header with overall state and controls;
- tabs for metrics, charts, errors, resources, and workers.

## Statistics

The statistics view shows metric tables grouped by metric name.

It includes:
- total requests;
- errors;
- error rate;
- average latency;
- median latency;
- p95 latency;
- p99 latency;
- requests per second.

## Charts

The charts view shows metric history over time.

It supports:
- metric selection;
- latency series selection;
- multiple time ranges;
- user-count overlays.

## Resources

The resources view shows:
- resource names;
- current resource counts;
- resource creation actions.

## Workers

The workers view shows:
- worker ID;
- health status;
- heartbeat age;
- assigned user count.

## Errors

The errors view shows:
- error events;
- traceback details;
- filtering by result category.
