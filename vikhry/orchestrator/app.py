from __future__ import annotations

import logging
from dataclasses import dataclass

import redis.asyncio as redis
import uvloop
from robyn import Robyn

from vikhry.orchestrator.api.routes import register_routes
from vikhry.orchestrator.models.settings import OrchestratorSettings
from vikhry.orchestrator.redis_repo.state_repo import TestStateRepository
from vikhry.orchestrator.services.lifecycle_service import LifecycleService
from vikhry.orchestrator.services.metrics_service import MetricsService
from vikhry.orchestrator.services.resource_service import ResourceService
from vikhry.orchestrator.services.worker_monitor import WorkerMonitor
from vikhry.orchestrator.services.user_orchestration import UserOrchestrationService
from vikhry.orchestrator.services.worker_presence import WorkerPresenceService

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class OrchestratorRuntime:
    redis_client: redis.Redis
    state_repo: TestStateRepository
    metrics_service: MetricsService
    resource_service: ResourceService
    lifecycle_service: LifecycleService
    worker_presence: WorkerPresenceService
    user_orchestration: UserOrchestrationService
    worker_monitor: WorkerMonitor


def build_app(settings: OrchestratorSettings) -> tuple[Robyn, OrchestratorRuntime]:
    app = Robyn(file_object=__file__)
    redis_client = redis.Redis.from_url(settings.redis_url, decode_responses=True)
    state_repo = TestStateRepository(redis_client)
    worker_presence = WorkerPresenceService(
        state_repo=state_repo,
        heartbeat_timeout_s=settings.heartbeat_timeout_s,
    )
    metrics_service = MetricsService(
        state_repo=state_repo,
        poll_interval_s=settings.metrics_poll_interval_s,
        window_s=settings.metrics_window_s,
        max_events_per_metric_per_poll=settings.metrics_max_events_per_poll,
        max_recent_events_per_metric=settings.metrics_recent_events_per_metric,
        max_subscriber_queue=settings.metrics_subscriber_queue_size,
    )
    resource_service = ResourceService(
        state_repo=state_repo,
        default_prepare_counts={},
    )
    user_orchestration = UserOrchestrationService(
        state_repo=state_repo,
        worker_presence=worker_presence,
    )
    lifecycle_service = LifecycleService(
        state_repo=state_repo,
        user_orchestration=user_orchestration,
        resource_service=resource_service,
    )
    worker_monitor = WorkerMonitor(
        scan_interval_s=settings.worker_scan_interval_s,
        heartbeat_timeout_s=settings.heartbeat_timeout_s,
        on_tick=worker_presence.refresh_cache,
    )

    runtime = OrchestratorRuntime(
        redis_client=redis_client,
        state_repo=state_repo,
        metrics_service=metrics_service,
        resource_service=resource_service,
        lifecycle_service=lifecycle_service,
        worker_presence=worker_presence,
        user_orchestration=user_orchestration,
        worker_monitor=worker_monitor,
    )

    register_routes(
        app=app,
        lifecycle_service=lifecycle_service,
        worker_presence=worker_presence,
        resource_service=resource_service,
        metrics_service=metrics_service,
    )

    @app.startup_handler
    async def on_startup() -> None:
        await runtime.state_repo.initialize_defaults()
        await runtime.worker_presence.refresh_cache()
        await runtime.metrics_service.start()
        await runtime.metrics_service.refresh_now()
        await runtime.worker_monitor.start()
        logger.info("orchestrator started")

    @app.shutdown_handler
    async def on_shutdown() -> None:
        await runtime.worker_monitor.stop()
        await runtime.metrics_service.stop()
        await runtime.redis_client.aclose()
        logger.info("orchestrator stopped")

    return app, runtime


def run_orchestrator(settings: OrchestratorSettings) -> None:
    uvloop.install()
    app, _ = build_app(settings)
    app.start(host=settings.host, port=settings.port)
