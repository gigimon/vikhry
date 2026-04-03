from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class WorkerSettings:
    redis_url: str = "redis://127.0.0.1:6379/0"
    worker_id: str = ""
    log_level: str = "INFO"
    heartbeat_interval_s: float = 3.0
    command_poll_timeout_s: float = 1.0
    graceful_stop_timeout_s: float = 5.0
    scenario: str = "vikhry.runtime.defaults:IdleVU"
    run_probes: bool = False
    http_base_url: str = ""
    vu_idle_sleep_s: float = 0.05
    vu_startup_jitter_ms: float = 5.0
