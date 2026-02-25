from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from redis.asyncio.client import PubSub

from vikhry.orchestrator.models.command import (
    AddUserPayload,
    CommandEnvelope,
    CommandType,
    RemoveUserPayload,
    StartTestPayload,
)
from vikhry.worker.models.state import WorkerPhase, WorkerRuntimeState
from vikhry.worker.redis_repo.state_repo import WorkerStateRepository

logger = logging.getLogger(__name__)


class WorkerCommandDispatcher:
    def __init__(
        self,
        state_repo: WorkerStateRepository,
        *,
        worker_id: str,
        runtime_state: WorkerRuntimeState,
        poll_timeout_s: float = 1.0,
        graceful_stop_timeout_s: float = 5.0,
        user_task_factory: Callable[[str], Awaitable[None]] | None = None,
    ) -> None:
        self._state_repo = state_repo
        self._worker_id = worker_id
        self._runtime_state = runtime_state
        self._poll_timeout_s = max(0.1, poll_timeout_s)
        self._graceful_stop_timeout_s = max(0.1, graceful_stop_timeout_s)
        self._user_task_factory = user_task_factory

        self._pubsub: PubSub | None = None
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._task and not self._task.done():
            return
        self._task = asyncio.create_task(self._run(), name=f"worker-commands:{self._worker_id}")

    async def stop(self) -> None:
        if not self._task:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        finally:
            self._task = None

    async def _run(self) -> None:
        self._pubsub = await self._state_repo.subscribe_commands(self._worker_id)
        logger.info("command subscription active (worker_id=%s)", self._worker_id)

        try:
            while True:
                message = await self._pubsub.get_message(
                    ignore_subscribe_messages=True,
                    timeout=self._poll_timeout_s,
                )
                if not message:
                    continue
                if message.get("type") != "message":
                    continue
                raw = message.get("data")
                if raw is None:
                    continue
                await self._handle_raw_message(raw)
        finally:
            await self._close_pubsub()

    async def _close_pubsub(self) -> None:
        if self._pubsub is None:
            return
        channel = self._state_repo.worker_command_channel(self._worker_id)
        try:
            await self._pubsub.unsubscribe(channel)
        except Exception:  # noqa: BLE001
            logger.debug("pubsub unsubscribe failed (worker_id=%s)", self._worker_id, exc_info=True)
        try:
            await self._pubsub.aclose()
        except Exception:  # noqa: BLE001
            logger.debug("pubsub close failed (worker_id=%s)", self._worker_id, exc_info=True)
        self._pubsub = None

    async def _handle_raw_message(self, raw: bytes | bytearray | memoryview | str) -> None:
        try:
            command = self._state_repo.decode_command(raw)
        except Exception:  # noqa: BLE001
            logger.warning("ignored invalid command (worker_id=%s)", self._worker_id, exc_info=True)
            return

        logger.info(
            "received command (worker_id=%s, command_id=%s, type=%s, epoch=%s)",
            self._worker_id,
            command.command_id,
            command.type.value,
            command.epoch,
        )

        try:
            await self._handle_command(command)
        except Exception:  # noqa: BLE001
            logger.exception(
                "command handling failed (worker_id=%s, command_id=%s, type=%s)",
                self._worker_id,
                command.command_id,
                command.type.value,
            )

    async def _handle_command(self, command: CommandEnvelope) -> None:
        command_type = command.type
        if command_type is CommandType.START_TEST:
            await self._handle_start_test(command)
            return
        if command_type is CommandType.STOP_TEST:
            await self._handle_stop_test(command)
            return
        if command_type is CommandType.ADD_USER:
            await self._handle_add_user(command)
            return
        if command_type is CommandType.REMOVE_USER:
            await self._handle_remove_user(command)
            return
        logger.warning("ignored unknown command type (worker_id=%s, type=%s)", self._worker_id, command_type)

    async def _handle_start_test(self, command: CommandEnvelope) -> None:
        payload = command.require_payload(StartTestPayload)
        state = self._runtime_state

        if command.epoch < state.current_epoch:
            logger.info(
                "ignored stale start_test (worker_id=%s, command_epoch=%s, current_epoch=%s)",
                self._worker_id,
                command.epoch,
                state.current_epoch,
            )
            return

        if command.epoch > state.current_epoch:
            await self._stop_all_user_tasks()
            state.assigned_users.clear()
            state.current_epoch = command.epoch

        await self._start_test_stub(payload.target_users)
        state.phase = WorkerPhase.RUNNING
        logger.info(
            "accepted start_test (worker_id=%s, epoch=%s, target_users=%s)",
            self._worker_id,
            state.current_epoch,
            payload.target_users,
        )

    async def _handle_stop_test(self, command: CommandEnvelope) -> None:
        state = self._runtime_state
        if command.epoch != state.current_epoch:
            logger.info(
                "ignored stop_test due to epoch mismatch (worker_id=%s, command_epoch=%s, current_epoch=%s)",
                self._worker_id,
                command.epoch,
                state.current_epoch,
            )
            return

        state.phase = WorkerPhase.STOPPING
        await self._stop_all_user_tasks()
        state.assigned_users.clear()
        state.phase = WorkerPhase.IDLE
        logger.info("accepted stop_test (worker_id=%s, epoch=%s)", self._worker_id, state.current_epoch)

    async def _handle_add_user(self, command: CommandEnvelope) -> None:
        state = self._runtime_state
        if command.epoch != state.current_epoch:
            logger.info(
                "ignored add_user due to epoch mismatch (worker_id=%s, command_epoch=%s, current_epoch=%s)",
                self._worker_id,
                command.epoch,
                state.current_epoch,
            )
            return
        if state.phase != WorkerPhase.RUNNING:
            logger.info(
                "ignored add_user while not running (worker_id=%s, phase=%s)",
                self._worker_id,
                state.phase.value,
            )
            return

        payload = command.require_payload(AddUserPayload)
        user_id = str(payload.user_id)
        if user_id in state.assigned_users:
            return
        state.assigned_users.add(user_id)
        task = self._spawn_user_task(user_id)
        if task is not None:
            state.user_tasks[user_id] = task

    async def _handle_remove_user(self, command: CommandEnvelope) -> None:
        state = self._runtime_state
        if command.epoch != state.current_epoch:
            logger.info(
                "ignored remove_user due to epoch mismatch (worker_id=%s, command_epoch=%s, current_epoch=%s)",
                self._worker_id,
                command.epoch,
                state.current_epoch,
            )
            return
        if state.phase not in {WorkerPhase.RUNNING, WorkerPhase.STOPPING}:
            logger.info(
                "ignored remove_user while not running/stopping (worker_id=%s, phase=%s)",
                self._worker_id,
                state.phase.value,
            )
            return

        payload = command.require_payload(RemoveUserPayload)
        user_id = str(payload.user_id)
        state.assigned_users.discard(user_id)
        user_task = state.user_tasks.pop(user_id, None)
        if user_task is not None:
            user_task.cancel()
            await asyncio.gather(user_task, return_exceptions=True)

    async def _stop_all_user_tasks(self) -> None:
        state = self._runtime_state
        tasks = list(state.user_tasks.values())
        if not tasks:
            state.user_tasks.clear()
            return

        for task in tasks:
            task.cancel()

        done, pending = await asyncio.wait(tasks, timeout=self._graceful_stop_timeout_s)
        if pending:
            logger.warning(
                "forcing cancellation of pending user tasks (worker_id=%s, pending=%s)",
                self._worker_id,
                len(pending),
            )
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
        if done:
            await asyncio.gather(*done, return_exceptions=True)
        state.user_tasks.clear()

    async def _start_test_stub(self, target_users: int) -> None:
        _ = target_users

    def _spawn_user_task(self, user_id: str) -> asyncio.Task[None] | None:
        if self._user_task_factory is None:
            return None
        coroutine = self._user_task_factory(user_id)
        task = asyncio.create_task(
            coroutine,
            name=f"worker-vu:{self._worker_id}:{user_id}",
        )
        task.add_done_callback(
            lambda finished_task: self._on_user_task_done(user_id, finished_task)
        )
        return task

    def _on_user_task_done(self, user_id: str, finished_task: asyncio.Task[Any]) -> None:
        current_task = self._runtime_state.user_tasks.get(user_id)
        if current_task is finished_task:
            self._runtime_state.user_tasks.pop(user_id, None)
        if finished_task.cancelled():
            return
        error = finished_task.exception()
        if error is not None:
            logger.error(
                "user task failed (worker_id=%s, user_id=%s)",
                self._worker_id,
                user_id,
                exc_info=(type(error), error, error.__traceback__),
            )
