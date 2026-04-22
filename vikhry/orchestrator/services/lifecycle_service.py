from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from vikhry.orchestrator.models.test_state import TestState
from vikhry.orchestrator.models.user import UserRuntimeStatus
from vikhry.orchestrator.redis_repo.state_repo import TestStateRepository
from vikhry.orchestrator.services.resource_service import ResourceService
from vikhry.orchestrator.services.user_orchestration import UserOrchestrationService

logger = logging.getLogger(__name__)


class InvalidStateTransitionError(RuntimeError):
    def __init__(self, action: str, expected: tuple[TestState, ...], current: TestState) -> None:
        expected_repr = ", ".join(state.value for state in expected)
        super().__init__(
            f"Action `{action}` is allowed only for [{expected_repr}], current={current.value}"
        )
        self.action = action
        self.expected = expected
        self.current = current


@dataclass(slots=True, frozen=True)
class StartTestResult:
    epoch: int
    target_users: int
    init_params: dict[str, Any]
    spawn_interval_ms: int
    prepare_result: dict[str, object]
    add_result: dict[str, object]
    start_result: dict[str, object]


@dataclass(slots=True, frozen=True)
class ChangeUsersResult:
    epoch: int
    target_users: int
    current_users: int
    spawn_interval_ms: int
    action: str
    result: dict[str, object]


@dataclass(slots=True, frozen=True)
class StopTestResult:
    epoch: int
    stop_result: dict[str, object]


class LifecycleService:
    """Strict lifecycle manager (fail-fast) for orchestrator v1."""

    def __init__(
        self,
        state_repo: TestStateRepository,
        user_orchestration: UserOrchestrationService,
        resource_service: ResourceService,
        on_before_start_test: Callable[[], Awaitable[None]] | None = None,
    ) -> None:
        self._state_repo = state_repo
        self._user_orchestration = user_orchestration
        self._resource_service = resource_service
        self._on_before_start_test = on_before_start_test

    async def state_snapshot(self) -> dict[str, str | int]:
        state = await self._state_repo.get_state()
        epoch = await self._state_repo.get_epoch()
        return {"state": state.value, "epoch": epoch}

    async def is_ready(self) -> bool:
        return (await self._state_repo.get_state()) in {
            TestState.IDLE,
            TestState.PREPARING,
            TestState.RUNNING,
            TestState.STOPPING,
        }

    async def start_test(
        self,
        target_users: int,
        init_params: dict[str, Any] | None = None,
        spawn_interval_ms: int = 0,
    ) -> StartTestResult:
        if target_users < 0:
            raise ValueError("target_users must be >= 0")
        if spawn_interval_ms < 0:
            raise ValueError("spawn_interval_ms must be >= 0")
        resolved_init_params = dict(init_params or {})
        logger.info(
            "start_test requested target_users=%s spawn_interval_ms=%s init_param_keys=%s",
            target_users,
            spawn_interval_ms,
            sorted(resolved_init_params.keys()),
        )

        epoch = await self._state_repo.start_preparing_and_bump_epoch()
        if epoch is None:
            current = await self._state_repo.get_state()
            raise InvalidStateTransitionError(
                action="start_test",
                expected=(TestState.IDLE,),
                current=current,
            )
        logger.info("start_test entered preparing epoch=%s target_users=%s", epoch, target_users)

        try:
            if self._on_before_start_test is not None:
                await self._on_before_start_test()
                logger.info("start_test cleared previous metrics epoch=%s", epoch)
            await self._state_repo.clear_users_timeline()
            prepare_result = await self._prepare_resources(target_users)
            start_result = await self._user_orchestration.send_start_test(
                epoch,
                target_users,
                resolved_init_params,
            )
            user_ids = list(range(1, target_users + 1))
            add_result = await self._user_orchestration.add_users(
                user_ids,
                epoch,
                spawn_interval_ms=spawn_interval_ms,
                expected_states=(TestState.PREPARING,),
                timeline_source="start_test",
                initial_user_count=0,
            )
            if not add_result.get("aborted"):
                await self._state_repo.set_all_users_status(
                    status=UserRuntimeStatus.RUNNING,
                    updated_at=self._now_ts(),
                )
                await self._state_repo.compare_and_set_state(
                    TestState.PREPARING, TestState.RUNNING
                )
            logger.info(
                "start_test completed epoch=%s target_users=%s workers_started=%s users_added=%s aborted=%s",
                epoch,
                target_users,
                start_result.get("delivered"),
                add_result.get("requested"),
                add_result.get("aborted"),
            )
            return StartTestResult(
                epoch=epoch,
                target_users=target_users,
                init_params=resolved_init_params,
                spawn_interval_ms=spawn_interval_ms,
                prepare_result=prepare_result,
                add_result=add_result,
                start_result=start_result,
            )
        except Exception:  # noqa: BLE001
            logger.exception(
                "start_test failed epoch=%s target_users=%s, attempting rollback",
                epoch,
                target_users,
            )
            try:
                await self._user_orchestration.send_stop_test(epoch)
            except Exception:  # noqa: BLE001
                logger.exception("failed to rollback worker run state on start_test error")
            # Rollback to stable state for v1 if start sequence failed.
            await self._state_repo.clear_users_data()
            await self._state_repo.set_state(TestState.IDLE)
            logger.info("start_test rollback completed epoch=%s state=%s", epoch, TestState.IDLE.value)
            raise

    async def change_users(
        self,
        target_users: int,
        spawn_interval_ms: int = 0,
    ) -> ChangeUsersResult:
        if target_users < 0:
            raise ValueError("target_users must be >= 0")
        if spawn_interval_ms < 0:
            raise ValueError("spawn_interval_ms must be >= 0")

        state = await self._state_repo.get_state()
        if state != TestState.RUNNING:
            raise InvalidStateTransitionError(
                action="change_users",
                expected=(TestState.RUNNING,),
                current=state,
            )

        epoch = await self._state_repo.get_epoch()
        current_user_ids = await self._state_repo.list_users()
        current_users = len(current_user_ids)

        if target_users == current_users:
            return ChangeUsersResult(
                epoch=epoch,
                target_users=target_users,
                current_users=current_users,
                spawn_interval_ms=spawn_interval_ms,
                action="noop",
                result={"requested": 0},
            )

        if target_users > current_users:
            prepare_result = await self._prepare_resources(target_users)
            user_ids = self._new_user_ids(
                existing_user_ids=current_user_ids,
                count=target_users - current_users,
            )
            add_result = await self._user_orchestration.add_users(
                user_ids,
                epoch,
                spawn_interval_ms=spawn_interval_ms,
                expected_states=(TestState.RUNNING,),
                timeline_source="change_users",
                initial_user_count=current_users,
            )
            add_result["prepare_result"] = prepare_result
            if not add_result.get("aborted"):
                await self._state_repo.set_all_users_status(
                    status=UserRuntimeStatus.RUNNING,
                    updated_at=self._now_ts(),
                )
            return ChangeUsersResult(
                epoch=epoch,
                target_users=target_users,
                current_users=current_users,
                spawn_interval_ms=spawn_interval_ms,
                action="add",
                result=add_result,
            )

        users_to_remove = self._users_for_removal(
            existing_user_ids=current_user_ids,
            count=current_users - target_users,
        )
        remove_result = await self._user_orchestration.remove_users(users_to_remove, epoch)
        await self._state_repo.append_users_timeline_event(
            epoch=epoch,
            users_count=target_users,
            source="change_users",
        )
        return ChangeUsersResult(
            epoch=epoch,
            target_users=target_users,
            current_users=current_users,
            spawn_interval_ms=spawn_interval_ms,
            action="remove",
            result=remove_result,
        )

    async def stop_test(self) -> StopTestResult:
        current = await self._state_repo.get_state()
        logger.info("stop_test requested current_state=%s", current.value)
        expected = (TestState.PREPARING, TestState.RUNNING)
        if current not in expected:
            raise InvalidStateTransitionError(
                action="stop_test",
                expected=expected,
                current=current,
            )

        changed = await self._state_repo.compare_and_set_state(current, TestState.STOPPING)
        if not changed:
            latest = await self._state_repo.get_state()
            raise InvalidStateTransitionError(
                action="stop_test",
                expected=expected,
                current=latest,
            )

        epoch = await self._state_repo.get_epoch()
        stop_result = await self._user_orchestration.send_stop_test(epoch)
        await self._state_repo.clear_users_data()
        await self._state_repo.append_users_timeline_event(
            epoch=epoch,
            users_count=0,
            source="stop_test",
        )
        await self._state_repo.set_state(TestState.IDLE)
        logger.info(
            "stop_test completed epoch=%s workers_stopped=%s state=%s",
            epoch,
            stop_result.get("delivered"),
            TestState.IDLE.value,
        )
        return StopTestResult(epoch=epoch, stop_result=stop_result)

    async def _prepare_resources(self, target_users: int) -> dict[str, object]:
        return await self._resource_service.prepare_for_start(target_users)

    @staticmethod
    def _new_user_ids(existing_user_ids: list[str], count: int) -> list[int]:
        max_user_id = 0
        for user_id in existing_user_ids:
            if user_id.isdigit():
                max_user_id = max(max_user_id, int(user_id))
        return [max_user_id + offset for offset in range(1, count + 1)]

    @staticmethod
    def _users_for_removal(existing_user_ids: list[str], count: int) -> list[str]:
        def sort_key(user_id: str) -> tuple[int, int | str]:
            return (0, int(user_id)) if user_id.isdigit() else (1, user_id)

        ordered = sorted(existing_user_ids, key=sort_key, reverse=True)
        return ordered[:count]

    @staticmethod
    def _now_ts() -> int:
        return int(time.time())
