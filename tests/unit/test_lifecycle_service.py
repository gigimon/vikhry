from __future__ import annotations

import pytest

from vikhry.orchestrator.models.test_state import TestState
from vikhry.orchestrator.services.lifecycle_service import (
    InvalidStateTransitionError,
    LifecycleService,
)


class _FakeStateRepo:
    def __init__(self) -> None:
        self.state = TestState.IDLE
        self.epoch = 0
        self.users: list[str] = []
        self.cleared = False
        self.users_timeline: list[dict[str, object]] = []

    async def get_state(self) -> TestState:
        return self.state

    async def set_state(self, state: TestState) -> None:
        self.state = state

    async def get_epoch(self) -> int:
        return self.epoch

    async def start_preparing_and_bump_epoch(self) -> int | None:
        if self.state != TestState.IDLE:
            return None
        self.state = TestState.PREPARING
        self.epoch += 1
        return self.epoch

    async def set_all_users_status(self, status, updated_at) -> int:  # noqa: ANN001
        return len(self.users)

    async def list_users(self) -> list[str]:
        return list(self.users)

    async def clear_users_data(self) -> None:
        self.users = []
        self.cleared = True

    async def clear_users_timeline(self) -> int:
        removed = 1 if self.users_timeline else 0
        self.users_timeline = []
        return removed

    async def append_users_timeline_event(
        self,
        *,
        epoch: int,
        users_count: int,
        source: str,
    ) -> str:
        self.users_timeline.append(
            {
                "epoch": epoch,
                "users_count": users_count,
                "source": source,
            }
        )
        return f"{len(self.users_timeline)}-0"

    async def compare_and_set_state(self, expected: TestState, new_state: TestState) -> bool:
        if self.state != expected:
            return False
        self.state = new_state
        return True


class _FakeUserOrchestration:
    def __init__(self, state_repo: _FakeStateRepo) -> None:
        self._state_repo = state_repo
        self.fail_start = False
        self.calls: list[str] = []

    async def add_users(self, user_ids, epoch):  # noqa: ANN001
        self.calls.append("add_users")
        self._state_repo.users.extend(str(user_id) for user_id in user_ids)
        return {"requested": len(user_ids)}

    async def remove_users(self, user_ids, epoch):  # noqa: ANN001
        for user_id in user_ids:
            user_id_str = str(user_id)
            if user_id_str in self._state_repo.users:
                self._state_repo.users.remove(user_id_str)
        return {"requested": len(user_ids)}

    async def send_start_test(self, epoch, target_users, init_params):  # noqa: ANN001
        self.calls.append("send_start_test")
        if self.fail_start:
            raise RuntimeError("start failed")
        return {"delivered": 1, "init_params": dict(init_params)}

    async def send_stop_test(self, epoch):  # noqa: ANN001
        return {"delivered": 1}


class _FakeResourceService:
    async def prepare_for_start(self, target_users: int) -> dict[str, object]:
        return {"target_users": target_users, "created": {}}


@pytest.mark.asyncio
async def test_lifecycle_happy_path_spec() -> None:
    repo = _FakeStateRepo()
    user_orchestration = _FakeUserOrchestration(repo)
    service = LifecycleService(
        state_repo=repo,  # type: ignore[arg-type]
        user_orchestration=user_orchestration,  # type: ignore[arg-type]
        resource_service=_FakeResourceService(),  # type: ignore[arg-type]
    )

    started = await service.start_test(target_users=3)
    assert started.epoch == 1
    assert started.init_params == {}
    assert user_orchestration.calls[:2] == ["send_start_test", "add_users"]
    assert repo.state == TestState.RUNNING
    assert len(repo.users) == 3
    assert repo.users_timeline[-1] == {"epoch": 1, "users_count": 3, "source": "start_test"}

    changed = await service.change_users(target_users=1)
    assert changed.action == "remove"
    assert len(repo.users) == 1
    assert repo.users_timeline[-1] == {"epoch": 1, "users_count": 1, "source": "change_users"}

    stopped = await service.stop_test()
    assert stopped.epoch == 1
    assert repo.state == TestState.IDLE
    assert repo.cleared is True
    assert repo.users_timeline[-1] == {"epoch": 1, "users_count": 0, "source": "stop_test"}


@pytest.mark.asyncio
async def test_lifecycle_start_calls_before_start_hook_spec() -> None:
    repo = _FakeStateRepo()
    user_orchestration = _FakeUserOrchestration(repo)
    hook_calls: list[str] = []

    async def before_start_hook() -> None:
        hook_calls.append("called")

    service = LifecycleService(
        state_repo=repo,  # type: ignore[arg-type]
        user_orchestration=user_orchestration,  # type: ignore[arg-type]
        resource_service=_FakeResourceService(),  # type: ignore[arg-type]
        on_before_start_test=before_start_hook,
    )

    await service.start_test(target_users=1)

    assert hook_calls == ["called"]


@pytest.mark.asyncio
async def test_lifecycle_start_rolls_back_on_failure_spec() -> None:
    repo = _FakeStateRepo()
    user_orchestration = _FakeUserOrchestration(repo)
    user_orchestration.fail_start = True
    service = LifecycleService(
        state_repo=repo,  # type: ignore[arg-type]
        user_orchestration=user_orchestration,  # type: ignore[arg-type]
        resource_service=_FakeResourceService(),  # type: ignore[arg-type]
    )

    with pytest.raises(RuntimeError):
        await service.start_test(target_users=2)

    assert repo.state == TestState.IDLE
    assert repo.cleared is True


@pytest.mark.asyncio
async def test_lifecycle_change_users_guard_spec() -> None:
    repo = _FakeStateRepo()
    service = LifecycleService(
        state_repo=repo,  # type: ignore[arg-type]
        user_orchestration=_FakeUserOrchestration(repo),  # type: ignore[arg-type]
        resource_service=_FakeResourceService(),  # type: ignore[arg-type]
    )

    with pytest.raises(InvalidStateTransitionError):
        await service.change_users(target_users=5)


@pytest.mark.asyncio
async def test_lifecycle_start_passes_init_params_to_orchestration_spec() -> None:
    repo = _FakeStateRepo()
    user_orchestration = _FakeUserOrchestration(repo)
    service = LifecycleService(
        state_repo=repo,  # type: ignore[arg-type]
        user_orchestration=user_orchestration,  # type: ignore[arg-type]
        resource_service=_FakeResourceService(),  # type: ignore[arg-type]
    )

    started = await service.start_test(
        target_users=1,
        init_params={"tenant": "demo", "warmup": 3},
    )

    assert started.init_params == {"tenant": "demo", "warmup": 3}
