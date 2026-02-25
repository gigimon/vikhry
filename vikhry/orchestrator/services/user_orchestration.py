from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from typing import Any
from uuid import uuid4

from pydantic import BaseModel

from vikhry.orchestrator.models.command import (
    AddUserPayload,
    CommandEnvelope,
    CommandType,
    RemoveUserPayload,
    StartTestPayload,
    StopTestPayload,
)
from vikhry.orchestrator.models.user import UserAssignment, UserRuntimeStatus
from vikhry.orchestrator.redis_repo.state_repo import TestStateRepository
from vikhry.orchestrator.services.worker_presence import WorkerPresenceService


def allocate_round_robin(
    user_ids: Sequence[int | str], worker_ids: Sequence[str]
) -> list[tuple[str, str]]:
    """Stateless round-robin allocation based on worker snapshot per request."""
    if not worker_ids:
        return []
    return [
        (str(user_id), worker_ids[index % len(worker_ids)])
        for index, user_id in enumerate(user_ids)
    ]


class UserOrchestrationService:
    def __init__(
        self,
        state_repo: TestStateRepository,
        worker_presence: WorkerPresenceService,
        now_fn: Callable[[], float] | None = None,
        command_id_fn: Callable[[], str] | None = None,
    ) -> None:
        self._state_repo = state_repo
        self._worker_presence = worker_presence
        self._now_fn = now_fn or time.time
        self._command_id_fn = command_id_fn or (lambda: str(uuid4()))

    async def add_users(self, user_ids: Sequence[int | str], epoch: int) -> dict[str, Any]:
        alive_workers = await self._worker_presence.require_alive_workers()
        allocations = allocate_round_robin(user_ids, alive_workers)
        added: list[dict[str, str]] = []
        skipped_existing: list[str] = []
        now_ts = self._now_ts()

        for user_id, worker_id in allocations:
            existing = await self._state_repo.get_user_assignment(user_id)
            if existing is not None:
                skipped_existing.append(user_id)
                continue

            assignment = UserAssignment(
                user_id=user_id,
                worker_id=worker_id,
                status=UserRuntimeStatus.PENDING,
                updated_at=now_ts,
            )
            await self._state_repo.add_user_assignment(assignment)
            await self._state_repo.publish_worker_command(
                worker_id,
                self._make_command(CommandType.ADD_USER, AddUserPayload(user_id=user_id), epoch),
            )
            added.append({"user_id": user_id, "worker_id": worker_id})

        return {
            "requested": len(user_ids),
            "added": added,
            "skipped_existing": skipped_existing,
            "alive_workers": list(alive_workers),
        }

    async def remove_users(self, user_ids: Sequence[int | str], epoch: int) -> dict[str, Any]:
        removed: list[dict[str, str]] = []
        skipped_missing: list[str] = []

        for user_id in user_ids:
            user_id_str = str(user_id)
            assignment = await self._state_repo.get_user_assignment(user_id_str)
            if assignment is None:
                skipped_missing.append(user_id_str)
                continue

            await self._state_repo.publish_worker_command(
                assignment.worker_id,
                self._make_command(
                    CommandType.REMOVE_USER,
                    RemoveUserPayload(user_id=user_id_str),
                    epoch,
                ),
            )
            await self._state_repo.remove_user_assignment(user_id_str)
            removed.append({"user_id": user_id_str, "worker_id": assignment.worker_id})

        return {
            "requested": len(user_ids),
            "removed": removed,
            "skipped_missing": skipped_missing,
        }

    async def send_start_test(
        self,
        epoch: int,
        target_users: int,
        init_params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        workers = await self._worker_presence.require_alive_workers()
        command = self._make_command(
            CommandType.START_TEST,
            StartTestPayload(
                target_users=target_users,
                init_params=dict(init_params or {}),
            ),
            epoch,
        )
        delivered = await self._publish_to_workers(workers, command)
        return {"workers": workers, "delivered": delivered}

    async def send_stop_test(self, epoch: int) -> dict[str, Any]:
        workers = await self._worker_presence.list_alive_workers()
        if not workers:
            return {"workers": [], "delivered": 0}
        command = self._make_command(CommandType.STOP_TEST, StopTestPayload(), epoch)
        delivered = await self._publish_to_workers(workers, command)
        return {"workers": workers, "delivered": delivered}

    async def _publish_to_workers(
        self, worker_ids: Sequence[str], command: CommandEnvelope
    ) -> int:
        delivered = 0
        for worker_id in worker_ids:
            delivered += await self._state_repo.publish_worker_command(worker_id, command)
        return delivered

    def _make_command(
        self,
        command_type: CommandType,
        payload: BaseModel,
        epoch: int,
    ) -> CommandEnvelope:
        return CommandEnvelope(
            type=command_type,
            command_id=self._command_id_fn(),
            epoch=epoch,
            sent_at=self._now_ts(),
            payload=payload,
        )

    def _now_ts(self) -> int:
        return int(self._now_fn())
