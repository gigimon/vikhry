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
from vikhry.worker.services.probes import WorkerProbeRuntime, load_probe_targets
from vikhry.worker.services.vu_runtime import WorkerVURuntime, load_vu_type

logger = logging.getLogger(__name__)


async def run_worker_async(settings: WorkerSettings) -> None:
    if not settings.worker_id:
        raise ValueError("worker_id must not be empty")

    logger.info(
        "worker startup initiated (worker_id=%s, redis_url=%s, scenario=%s, run_probes=%s)",
        settings.worker_id,
        settings.redis_url,
        settings.scenario,
        settings.run_probes,
    )
    vu_type = load_vu_type(settings.scenario)
    probe_targets = load_probe_targets(settings.scenario) if settings.run_probes else ()

    shutdown_event = asyncio.Event()
    _install_signal_handlers(shutdown_event)

    redis_client = redis.Redis.from_url(settings.redis_url, decode_responses=True)
    connected = await _wait_for_redis_or_retry(
        redis_client=redis_client,
        redis_url=settings.redis_url,
        retry_delay_s=5.0,
        worker_id=settings.worker_id,
        shutdown_event=shutdown_event,
    )
    if not connected:
        await redis_client.aclose()
        return
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
        startup_jitter_s=max(0.0, settings.vu_startup_jitter_ms / 1000.0),
    )
    heartbeat = WorkerHeartbeatService(
        state_repo=state_repo,
        worker_id=settings.worker_id,
        interval_s=settings.heartbeat_interval_s,
    )
    probe_runtime = WorkerProbeRuntime(
        state_repo,
        runtime_state=runtime_state,
        worker_id=settings.worker_id,
        probes=probe_targets,
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
        await probe_runtime.start()
        await dispatcher.start()
        logger.info("worker started (worker_id=%s)", settings.worker_id)
        await shutdown_event.wait()
    finally:
        await dispatcher.stop()
        await probe_runtime.stop()
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
    _configure_logging(settings.log_level)
    uvloop.install()
    asyncio.run(run_worker_async(settings))


def _install_signal_handlers(shutdown_event: asyncio.Event) -> None:
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, shutdown_event.set)
        except NotImplementedError:
            continue


def _configure_logging(log_level: str) -> None:
    normalized_level = str(log_level).strip().upper() or "INFO"
    resolved_level = getattr(logging, normalized_level, None)
    invalid_level = not isinstance(resolved_level, int)
    if not isinstance(resolved_level, int):
        resolved_level = logging.INFO
    logging.basicConfig(
        level=resolved_level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        force=True,
    )
    if invalid_level:
        logger.warning("unknown log level `%s`, falling back to INFO", log_level)


async def _wait_for_redis_or_retry(
    *,
    redis_client: redis.Redis,
    redis_url: str,
    retry_delay_s: float,
    worker_id: str,
    shutdown_event: asyncio.Event | None = None,
) -> bool:
    attempt = 1
    while True:
        try:
            await redis_client.ping()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.error(
                "worker failed to connect to redis "
                "(worker_id=%s, redis_url=%s, attempt=%s): %s. Retrying in %.1fs",
                worker_id,
                redis_url,
                attempt,
                exc,
                retry_delay_s,
            )
            attempt += 1
            if shutdown_event is None:
                await asyncio.sleep(retry_delay_s)
                continue
            try:
                await asyncio.wait_for(shutdown_event.wait(), timeout=retry_delay_s)
            except TimeoutError:
                continue
            logger.info(
                "worker shutdown requested while waiting for redis "
                "(worker_id=%s, redis_url=%s)",
                worker_id,
                redis_url,
            )
            return False

        if attempt > 1:
            logger.info(
                "worker connected to redis after retries "
                "(worker_id=%s, redis_url=%s, attempts=%s)",
                worker_id,
                redis_url,
                attempt,
            )
        return True
