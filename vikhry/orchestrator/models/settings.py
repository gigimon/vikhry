from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class OrchestratorSettings:
    host: str = "127.0.0.1"
    port: int = 8080
    redis_url: str = "redis://127.0.0.1:6379/0"
    heartbeat_timeout_s: int = 15
    worker_scan_interval_s: int = 5
    metrics_poll_interval_s: float = 1.0
    metrics_window_s: int = 60
    metrics_max_events_per_poll: int = 300
    metrics_recent_events_per_metric: int = 1000
    metrics_subscriber_queue_size: int = 64
