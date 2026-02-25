from __future__ import annotations

import asyncio

import pytest

from vikhry.orchestrator.models.command import (
    AddUserPayload,
    CommandEnvelope,
    CommandType,
    RemoveUserPayload,
    StartTestPayload,
    StopTestPayload,
)
from vikhry.worker.models.state import WorkerPhase, WorkerRuntimeState
from vikhry.worker.services.command_dispatcher import WorkerCommandDispatcher


class _FakeWorkerStateRepo:
    def __init__(self) -> None:
        self.raise_decode_error = False

    def decode_command(self, raw: bytes | bytearray | memoryview | str) -> CommandEnvelope:
        if self.raise_decode_error:
            raise ValueError("decode error")
        return CommandEnvelope.from_json_bytes(raw)

    @staticmethod
    def worker_command_channel(worker_id: str) -> str:
        return f"worker:{worker_id}:commands"


def _command(
    command_type: CommandType,
    *,
    epoch: int,
    payload: object,
    command_id: str = "cmd-1",
) -> CommandEnvelope:
    return CommandEnvelope(
        type=command_type,
        command_id=command_id,
        epoch=epoch,
        sent_at=1,
        payload=payload,
    )


@pytest.mark.asyncio
async def test_dispatcher_happy_path_idempotent_user_ops_spec() -> None:
    state = WorkerRuntimeState()
    dispatcher = WorkerCommandDispatcher(
        _FakeWorkerStateRepo(),  # type: ignore[arg-type]
        worker_id="w1",
        runtime_state=state,
    )

    await dispatcher._handle_command(  # noqa: SLF001
        _command(
            CommandType.START_TEST,
            epoch=1,
            payload=StartTestPayload(target_users=2),
            command_id="start-1",
        )
    )
    assert state.phase == WorkerPhase.RUNNING
    assert state.current_epoch == 1

    await dispatcher._handle_command(  # noqa: SLF001
        _command(
            CommandType.ADD_USER,
            epoch=1,
            payload=AddUserPayload(user_id=1),
            command_id="add-1",
        )
    )
    await dispatcher._handle_command(  # noqa: SLF001
        _command(
            CommandType.ADD_USER,
            epoch=1,
            payload=AddUserPayload(user_id=1),
            command_id="add-1-repeat",
        )
    )
    await dispatcher._handle_command(  # noqa: SLF001
        _command(
            CommandType.ADD_USER,
            epoch=1,
            payload=AddUserPayload(user_id=2),
            command_id="add-2",
        )
    )
    assert state.assigned_users == {"1", "2"}

    await dispatcher._handle_command(  # noqa: SLF001
        _command(
            CommandType.REMOVE_USER,
            epoch=1,
            payload=RemoveUserPayload(user_id=1),
            command_id="remove-1",
        )
    )
    await dispatcher._handle_command(  # noqa: SLF001
        _command(
            CommandType.REMOVE_USER,
            epoch=1,
            payload=RemoveUserPayload(user_id=1),
            command_id="remove-1-repeat",
        )
    )
    assert state.assigned_users == {"2"}

    await dispatcher._handle_command(  # noqa: SLF001
        _command(
            CommandType.STOP_TEST,
            epoch=1,
            payload=StopTestPayload(),
            command_id="stop-1",
        )
    )
    assert state.phase == WorkerPhase.IDLE
    assert state.assigned_users == set()


@pytest.mark.asyncio
async def test_dispatcher_epoch_gating_and_reset_on_new_start_spec() -> None:
    state = WorkerRuntimeState()
    dispatcher = WorkerCommandDispatcher(
        _FakeWorkerStateRepo(),  # type: ignore[arg-type]
        worker_id="w1",
        runtime_state=state,
    )

    await dispatcher._handle_command(  # noqa: SLF001
        _command(
            CommandType.START_TEST,
            epoch=2,
            payload=StartTestPayload(target_users=1),
            command_id="start-2",
        )
    )
    await dispatcher._handle_command(  # noqa: SLF001
        _command(
            CommandType.ADD_USER,
            epoch=2,
            payload=AddUserPayload(user_id=10),
            command_id="add-10",
        )
    )
    assert state.assigned_users == {"10"}

    await dispatcher._handle_command(  # noqa: SLF001
        _command(
            CommandType.ADD_USER,
            epoch=1,
            payload=AddUserPayload(user_id=999),
            command_id="add-stale",
        )
    )
    await dispatcher._handle_command(  # noqa: SLF001
        _command(
            CommandType.STOP_TEST,
            epoch=1,
            payload=StopTestPayload(),
            command_id="stop-stale",
        )
    )
    assert state.phase == WorkerPhase.RUNNING
    assert state.current_epoch == 2
    assert state.assigned_users == {"10"}

    await dispatcher._handle_command(  # noqa: SLF001
        _command(
            CommandType.START_TEST,
            epoch=3,
            payload=StartTestPayload(target_users=0),
            command_id="start-3",
        )
    )
    assert state.phase == WorkerPhase.RUNNING
    assert state.current_epoch == 3
    assert state.assigned_users == set()


@pytest.mark.asyncio
async def test_dispatcher_ignores_invalid_raw_command_spec() -> None:
    repo = _FakeWorkerStateRepo()
    repo.raise_decode_error = True
    state = WorkerRuntimeState()
    dispatcher = WorkerCommandDispatcher(
        repo,  # type: ignore[arg-type]
        worker_id="w1",
        runtime_state=state,
    )

    await dispatcher._handle_raw_message(b'{"bad":')  # noqa: SLF001
    assert state.phase == WorkerPhase.IDLE
    assert state.current_epoch == 0
    assert state.assigned_users == set()


@pytest.mark.asyncio
async def test_dispatcher_starts_and_stops_user_task_with_runtime_factory_spec() -> None:
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def user_runtime(_user_id: str) -> None:
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    state = WorkerRuntimeState()
    dispatcher = WorkerCommandDispatcher(
        _FakeWorkerStateRepo(),  # type: ignore[arg-type]
        worker_id="w1",
        runtime_state=state,
        user_task_factory=user_runtime,
    )

    await dispatcher._handle_command(  # noqa: SLF001
        _command(
            CommandType.START_TEST,
            epoch=1,
            payload=StartTestPayload(target_users=1),
            command_id="start-1",
        )
    )
    await dispatcher._handle_command(  # noqa: SLF001
        _command(
            CommandType.ADD_USER,
            epoch=1,
            payload=AddUserPayload(user_id=1),
            command_id="add-1",
        )
    )

    await asyncio.wait_for(started.wait(), timeout=1.0)
    assert "1" in state.user_tasks

    await dispatcher._handle_command(  # noqa: SLF001
        _command(
            CommandType.REMOVE_USER,
            epoch=1,
            payload=RemoveUserPayload(user_id=1),
            command_id="remove-1",
        )
    )
    await asyncio.wait_for(cancelled.wait(), timeout=1.0)
    assert "1" not in state.user_tasks
