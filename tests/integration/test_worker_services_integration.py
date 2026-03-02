from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any

import pytest
import redis.asyncio as redis

from vikhry.orchestrator.models.command import (
    AddUserPayload,
    CommandEnvelope,
    CommandType,
    RemoveUserPayload,
    StartTestPayload,
    StopTestPayload,
)
from vikhry.orchestrator.models.worker import WorkerHealthStatus
from vikhry.worker.models.state import WorkerPhase, WorkerRuntimeState
from vikhry.worker.redis_repo.state_repo import WorkerStateRepository
from vikhry.worker.services.command_dispatcher import WorkerCommandDispatcher
from vikhry.worker.services.heartbeat import WorkerHeartbeatService

pytestmark = pytest.mark.integration


def _command(
    command_type: CommandType,
    *,
    epoch: int,
    payload: object,
    command_id: str,
) -> CommandEnvelope:
    return CommandEnvelope(
        type=command_type,
        command_id=command_id,
        epoch=epoch,
        sent_at=int(time.time()),
        payload=payload,
    )


async def _wait_until(
    predicate: Callable[[], bool | Awaitable[Any]],
    *,
    timeout_s: float = 2.0,
    poll_interval_s: float = 0.05,
) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        result = predicate()
        if asyncio.iscoroutine(result):
            result = await result
        if bool(result):
            return
        await asyncio.sleep(poll_interval_s)
    raise AssertionError("condition not met before timeout")


@pytest.mark.asyncio
async def test_dispatcher_processes_commands_sequentially_spec(
    redis_client: redis.Redis,
) -> None:
    worker_id = "w-int"
    repo = WorkerStateRepository(redis_client)
    state = WorkerRuntimeState()
    dispatcher = WorkerCommandDispatcher(
        repo,
        worker_id=worker_id,
        runtime_state=state,
        poll_timeout_s=0.1,
        graceful_stop_timeout_s=0.2,
    )
    channel = repo.worker_command_channel(worker_id)

    await dispatcher.start()

    try:
        await redis_client.publish(
            channel,
            _command(
                CommandType.ADD_USER,
                epoch=1,
                payload=AddUserPayload(user_id=1),
                command_id="add-before-start",
            ).to_json_bytes(),
        )
        await asyncio.sleep(0.1)
        assert state.phase == WorkerPhase.IDLE
        assert state.assigned_users == set()

        await redis_client.publish(
            channel,
            _command(
                CommandType.START_TEST,
                epoch=1,
                payload=StartTestPayload(target_users=2),
                command_id="start-1",
            ).to_json_bytes(),
        )
        await _wait_until(lambda: state.phase == WorkerPhase.RUNNING and state.current_epoch == 1)

        await redis_client.publish(
            channel,
            _command(
                CommandType.ADD_USER,
                epoch=1,
                payload=AddUserPayload(user_id=1),
                command_id="add-1",
            ).to_json_bytes(),
        )
        await redis_client.publish(
            channel,
            _command(
                CommandType.ADD_USER,
                epoch=1,
                payload=AddUserPayload(user_id=1),
                command_id="add-1-duplicate",
            ).to_json_bytes(),
        )
        await redis_client.publish(
            channel,
            _command(
                CommandType.ADD_USER,
                epoch=1,
                payload=AddUserPayload(user_id=2),
                command_id="add-2",
            ).to_json_bytes(),
        )
        await _wait_until(lambda: state.assigned_users == {"1", "2"})

        await redis_client.publish(
            channel,
            _command(
                CommandType.ADD_USER,
                epoch=0,
                payload=AddUserPayload(user_id=999),
                command_id="add-stale",
            ).to_json_bytes(),
        )
        await asyncio.sleep(0.1)
        assert state.assigned_users == {"1", "2"}

        await redis_client.publish(
            channel,
            _command(
                CommandType.REMOVE_USER,
                epoch=1,
                payload=RemoveUserPayload(user_id=1),
                command_id="remove-1",
            ).to_json_bytes(),
        )
        await _wait_until(lambda: state.assigned_users == {"2"})

        await redis_client.publish(
            channel,
            _command(
                CommandType.STOP_TEST,
                epoch=1,
                payload=StopTestPayload(),
                command_id="stop-1",
            ).to_json_bytes(),
        )
        await _wait_until(lambda: state.phase == WorkerPhase.IDLE and not state.assigned_users)
    finally:
        await dispatcher.stop()


@pytest.mark.asyncio
async def test_heartbeat_writes_status_key_spec(redis_client: redis.Redis) -> None:
    worker_id = "w-heart"
    repo = WorkerStateRepository(redis_client)
    service = WorkerHeartbeatService(
        repo,
        worker_id=worker_id,
        interval_s=0.05,
    )

    await repo.register_worker(worker_id)
    await service.start()
    try:
        status_key = repo.worker_status_key(worker_id)
        await _wait_until(
            lambda: redis_client.hgetall(status_key),
            timeout_s=2.0,
        )
        raw = await redis_client.hgetall(status_key)
        assert raw.get("status") == WorkerHealthStatus.HEALTHY.value
        assert "cpu_percent" in raw
        assert "rss_bytes" in raw
        assert "total_ram_bytes" in raw
    finally:
        await service.stop()

    await service.mark_unhealthy()
    raw_after = await redis_client.hgetall(repo.worker_status_key(worker_id))
    assert raw_after.get("status") == WorkerHealthStatus.UNHEALTHY.value
