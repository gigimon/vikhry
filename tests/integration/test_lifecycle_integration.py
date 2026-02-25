from __future__ import annotations

import time

import pytest

from vikhry.orchestrator.models.worker import WorkerHealthStatus, WorkerStatus
from vikhry.orchestrator.redis_repo.state_repo import TestStateRepository
from vikhry.orchestrator.services.lifecycle_service import LifecycleService
from vikhry.orchestrator.services.resource_service import ResourceService
from vikhry.orchestrator.services.user_orchestration import UserOrchestrationService
from vikhry.orchestrator.services.worker_presence import (
    NoAliveWorkersError,
    WorkerPresenceService,
)

pytestmark = pytest.mark.integration


def _build_services(
    state_repo: TestStateRepository,
    *,
    now_ts: int,
    heartbeat_timeout_s: int = 15,
) -> tuple[WorkerPresenceService, UserOrchestrationService, LifecycleService]:
    presence = WorkerPresenceService(
        state_repo=state_repo,
        heartbeat_timeout_s=heartbeat_timeout_s,
        now_fn=lambda: float(now_ts),
    )
    orchestration = UserOrchestrationService(
        state_repo=state_repo,
        worker_presence=presence,
        now_fn=lambda: float(now_ts),
    )
    lifecycle = LifecycleService(
        state_repo=state_repo,
        user_orchestration=orchestration,
        resource_service=ResourceService(state_repo),
    )
    return presence, orchestration, lifecycle


@pytest.mark.asyncio
async def test_start_change_stop_happy_path_spec(state_repo: TestStateRepository) -> None:
    now_ts = 10_000
    _, _, lifecycle = _build_services(state_repo, now_ts=now_ts)

    await state_repo.register_worker("w1")
    await state_repo.set_worker_status(
        "w1",
        WorkerStatus(status=WorkerHealthStatus.HEALTHY, last_heartbeat=now_ts),
    )

    started = await lifecycle.start_test(target_users=3)
    assert started.epoch == 1
    assert (await state_repo.get_state()).value == "RUNNING"
    assert await state_repo.list_users() == ["1", "2", "3"]

    changed_up = await lifecycle.change_users(target_users=5)
    assert changed_up.action == "add"
    assert await state_repo.list_users() == ["1", "2", "3", "4", "5"]

    changed_down = await lifecycle.change_users(target_users=2)
    assert changed_down.action == "remove"
    assert await state_repo.list_users() == ["1", "2"]

    stopped = await lifecycle.stop_test()
    assert stopped.epoch == 1
    assert (await state_repo.get_state()).value == "IDLE"
    assert await state_repo.list_users() == []


@pytest.mark.asyncio
async def test_start_fails_without_alive_workers_and_rolls_back_spec(
    state_repo: TestStateRepository,
) -> None:
    _, _, lifecycle = _build_services(state_repo, now_ts=10_000)

    with pytest.raises(NoAliveWorkersError):
        await lifecycle.start_test(target_users=1)

    assert (await state_repo.get_state()).value == "IDLE"
    assert await state_repo.list_users() == []
    assert await state_repo.get_epoch() == 1


@pytest.mark.asyncio
async def test_start_fails_with_stale_heartbeat_spec(state_repo: TestStateRepository) -> None:
    _, _, lifecycle = _build_services(state_repo, now_ts=10_000, heartbeat_timeout_s=5)

    await state_repo.register_worker("w1")
    await state_repo.set_worker_status(
        "w1",
        WorkerStatus(status=WorkerHealthStatus.HEALTHY, last_heartbeat=9_900),
    )

    with pytest.raises(NoAliveWorkersError):
        await lifecycle.start_test(target_users=1)

    assert (await state_repo.get_state()).value == "IDLE"
    assert await state_repo.list_users() == []


@pytest.mark.asyncio
async def test_duplicate_add_and_remove_commands_are_idempotent_spec(
    state_repo: TestStateRepository,
) -> None:
    now_ts = 10_000
    _, orchestration, _ = _build_services(state_repo, now_ts=now_ts)

    await state_repo.register_worker("w1")
    await state_repo.set_worker_status(
        "w1",
        WorkerStatus(status=WorkerHealthStatus.HEALTHY, last_heartbeat=now_ts),
    )

    first_add = await orchestration.add_users([1, 2], epoch=1)
    second_add = await orchestration.add_users([1, 2], epoch=1)
    assert len(first_add["added"]) == 2
    assert second_add["skipped_existing"] == ["1", "2"]
    assert await state_repo.list_users() == ["1", "2"]

    first_remove = await orchestration.remove_users([2], epoch=1)
    second_remove = await orchestration.remove_users([2], epoch=1)
    assert len(first_remove["removed"]) == 1
    assert second_remove["skipped_missing"] == ["2"]
    assert await state_repo.list_users() == ["1"]


@pytest.mark.asyncio
async def test_start_sends_start_before_add_commands_spec(
    state_repo: TestStateRepository,
) -> None:
    now_ts = 10_000
    _, _, lifecycle = _build_services(state_repo, now_ts=now_ts)

    await state_repo.register_worker("w1")
    await state_repo.set_worker_status(
        "w1",
        WorkerStatus(status=WorkerHealthStatus.HEALTHY, last_heartbeat=now_ts),
    )

    channel = state_repo.worker_command_channel("w1")
    pubsub = state_repo._redis.pubsub(ignore_subscribe_messages=True)  # noqa: SLF001
    await pubsub.subscribe(channel)

    try:
        await lifecycle.start_test(target_users=2)

        command_types: list[str] = []
        deadline = time.monotonic() + 2.0
        while len(command_types) < 3 and time.monotonic() < deadline:
            message = await pubsub.get_message(ignore_subscribe_messages=True, timeout=0.2)
            if not message or message.get("type") != "message":
                continue
            raw = message.get("data")
            if raw is None:
                continue
            command_types.append(state_repo.decode_command(raw).type.value)
    finally:
        await pubsub.unsubscribe(channel)
        await pubsub.aclose()

    assert command_types[:3] == ["start_test", "add_user", "add_user"]
