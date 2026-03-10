---
title: Introduction
description: What vikhry is and how its main runtime components fit together.
sidebar:
  order: 1
---

`vikhry` is an async distributed load-testing framework built for high concurrency, horizontal scaling, and workloads that require globally unique resources.

It is designed for:

- HTTP and JSON-RPC load testing
- distributed service testing
- scenarios with many unique users or resources
- running load across multiple machines
- live metrics visualization during a test

## Runtime structure

At runtime, `vikhry` is built around four core parts:

### Redis

Redis is the shared coordination layer. It stores test state, worker presence, user assignments, resource pools, and metric streams.

### Orchestrator

The orchestrator is the control plane. It exposes the HTTP and WebSocket API, serves the built-in UI, tracks the test lifecycle, and coordinates workers.

### Worker

Workers execute virtual users, run scenario steps, publish metrics, and acquire or release shared resources.

### CLI

The CLI is the main entrypoint for local operation. It can:

- start and stop the orchestrator
- start and stop workers
- start, stop, or scale a test
- launch a local all-in-one stack with `vikhry infra up`

## Key dependencies

Two runtime pieces are backed by Rust-based dependencies:

- the HTTP client layer is built on top of `pyreqwest`
- the web server layer is built on top of `Robyn`

This is why `vikhry` uses a Python scenario DSL while still relying on Rust-backed networking components in the runtime.
