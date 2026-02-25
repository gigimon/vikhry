from __future__ import annotations

import asyncio
import logging
import signal

import redis.asyncio as redis
import uvloop

from vikhry.worker.models.settings import WorkerSettings
from vikhry.worker.models.state import WorkerRuntimeState
from vikhry.worker.redis_repo.state_repo import WorkerStateRepository
from vikhry.worker.services.command_dispatcher import WorkerCommandDispatcher
from vikhry.worker.services.heartbeat import WorkerHeartbeatService
from vikhry.worker.services.vu_runtime import WorkerVURuntime, load_vu_type

logger = logging.getLogger(__name__)


async def run_worker_async(settings: WorkerSettings) -> None:
    if not settings.worker_id:
        raise ValueError("worker_id must not be empty")

    logger.info(
        "worker startup initiated (worker_id=%s, redis_url=%s, scenario=%s)",
        settings.worker_id,
        settings.redis_url,
        settings.scenario,
    )
    vu_type = load_vu_type(settings.scenario)

    shutdown_event = asyncio.Event()
    _install_signal_handlers(shutdown_event)

    redis_client = redis.Redis.from_url(settings.redis_url, decode_responses=True)
    try:
        await redis_client.ping()
    except Exception:  # noqa: BLE001
        logger.exception(
            "worker failed to connect to redis (worker_id=%s, redis_url=%s)",
            settings.worker_id,
            settings.redis_url,
        )
        await redis_client.aclose()
        raise
    logger.info(
        "worker connected to redis (worker_id=%s, redis_url=%s)",
        settings.worker_id,
        settings.redis_url,
    )

    state_repo = WorkerStateRepository(redis_client)
    runtime_state = WorkerRuntimeState()
    vu_runtime = WorkerVURuntime(
        state_repo,
        worker_id=settings.worker_id,
        vu_type=vu_type,
        http_base_url=settings.http_base_url,
        idle_sleep_s=settings.vu_idle_sleep_s,
    )
    heartbeat = WorkerHeartbeatService(
        state_repo=state_repo,
        worker_id=settings.worker_id,
        interval_s=settings.heartbeat_interval_s,
    )
    dispatcher = WorkerCommandDispatcher(
        state_repo=state_repo,
        worker_id=settings.worker_id,
        runtime_state=runtime_state,
        poll_timeout_s=settings.command_poll_timeout_s,
        graceful_stop_timeout_s=settings.graceful_stop_timeout_s,
        user_task_factory=vu_runtime.run_user,
    )

    try:
        await state_repo.register_worker(settings.worker_id)
        await heartbeat.mark_healthy()
        await heartbeat.start()
        await dispatcher.start()
        logger.info("worker started (worker_id=%s)", settings.worker_id)
        await shutdown_event.wait()
    finally:
        await dispatcher.stop()
        await heartbeat.stop()
        try:
            await heartbeat.mark_unhealthy()
        except Exception:  # noqa: BLE001
            logger.exception("failed to mark worker unhealthy (worker_id=%s)", settings.worker_id)
        try:
            await state_repo.unregister_worker(settings.worker_id)
        except Exception:  # noqa: BLE001
            logger.exception("worker unregister failed (worker_id=%s)", settings.worker_id)
        await redis_client.aclose()
        logger.info("worker stopped (worker_id=%s)", settings.worker_id)


def run_worker(settings: WorkerSettings) -> None:
    _configure_logging()
    uvloop.install()
    asyncio.run(run_worker_async(settings))


def _install_signal_handlers(shutdown_event: asyncio.Event) -> None:
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, shutdown_event.set)
        except NotImplementedError:
            continue


def _configure_logging() -> None:
    root = logging.getLogger()
    if root.handlers:
        return
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
