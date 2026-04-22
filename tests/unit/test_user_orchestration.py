from __future__ import annotations

import pytest

from vikhry.orchestrator.models.command import CommandEnvelope, CommandType
from vikhry.orchestrator.models.test_state import TestState
from vikhry.orchestrator.models.user import UserAssignment
from vikhry.orchestrator.services.user_orchestration import (
    UserOrchestrationService,
    allocate_round_robin,
)


def test_allocate_round_robin_spec() -> None:
    allocations = allocate_round_robin(
        user_ids=[1, 2, 3, 4, 5],
        worker_ids=["w1", "w2"],
    )

    assert allocations == [
        ("1", "w1"),
        ("2", "w2"),
        ("3", "w1"),
        ("4", "w2"),
        ("5", "w1"),
    ]


def test_allocate_round_robin_empty_workers_spec() -> None:
    assert allocate_round_robin(user_ids=[1, 2], worker_ids=[]) == []


class _FakeStateRepo:
    def __init__(self) -> None:
        self.state: TestState = TestState.PREPARING
        self.assignments: dict[str, UserAssignment] = {}
        self.published: list[tuple[str, CommandEnvelope]] = []
        self.timeline: list[dict[str, object]] = []

    async def get_user_assignment(self, user_id: str) -> UserAssignment | None:
        return self.assignments.get(str(user_id))

    async def add_user_assignment(self, assignment: UserAssignment) -> None:
        self.assignments[str(assignment.user_id)] = assignment

    async def publish_worker_command(self, worker_id: str, command: CommandEnvelope) -> int:
        self.published.append((worker_id, command))
        return 1

    async def append_users_timeline_event(
        self,
        *,
        epoch: int,
        users_count: int,
        source: str,
    ) -> str:
        self.timeline.append(
            {"epoch": epoch, "users_count": users_count, "source": source}
        )
        return f"{len(self.timeline)}-0"

    async def get_state(self) -> TestState:
        return self.state


class _FakeWorkerPresence:
    def __init__(self, workers: list[str]) -> None:
        self._workers = workers

    async def require_alive_workers(self) -> list[str]:
        return list(self._workers)


def _make_service(
    repo: _FakeStateRepo,
    workers: list[str],
    sleeps: list[float] | None = None,
    on_sleep=None,  # noqa: ANN001
) -> UserOrchestrationService:
    async def record_sleep(delay: float) -> None:
        if sleeps is not None:
            sleeps.append(delay)
        if on_sleep is not None:
            await on_sleep(delay)

    return UserOrchestrationService(
        state_repo=repo,  # type: ignore[arg-type]
        worker_presence=_FakeWorkerPresence(workers),  # type: ignore[arg-type]
        sleep_fn=record_sleep,
        now_fn=lambda: 1.0,
        command_id_fn=lambda: "cmd",
    )


@pytest.mark.asyncio
async def test_add_users_with_no_interval_does_not_sleep() -> None:
    repo = _FakeStateRepo()
    sleeps: list[float] = []
    service = _make_service(repo, ["w1", "w2"], sleeps=sleeps)

    result = await service.add_users(
        [1, 2, 3],
        epoch=5,
        spawn_interval_ms=0,
    )

    assert sleeps == []
    assert len(repo.published) == 3
    assert all(env.type == CommandType.ADD_USER for _, env in repo.published)
    assert result["aborted"] is False
    assert result["spawn_interval_ms"] == 0


@pytest.mark.asyncio
async def test_add_users_paced_sleeps_between_publishes_but_not_after_last() -> None:
    repo = _FakeStateRepo()
    sleeps: list[float] = []
    service = _make_service(repo, ["w1"], sleeps=sleeps)

    await service.add_users(
        [1, 2, 3],
        epoch=5,
        spawn_interval_ms=150,
        expected_states=(TestState.PREPARING,),
        timeline_source="start_test",
    )

    assert sleeps == [0.15, 0.15]
    assert len(repo.published) == 3


@pytest.mark.asyncio
async def test_add_users_paced_aborts_when_state_changes() -> None:
    repo = _FakeStateRepo()

    async def flip_state_after_first_sleep(_: float) -> None:
        repo.state = TestState.STOPPING

    service = _make_service(
        repo,
        ["w1"],
        on_sleep=flip_state_after_first_sleep,
    )

    result = await service.add_users(
        [1, 2, 3, 4, 5],
        epoch=5,
        spawn_interval_ms=10,
        expected_states=(TestState.PREPARING,),
    )

    assert result["aborted"] is True
    # First publish, then sleep, state-flip detected — loop breaks before publishing #2.
    assert len(repo.published) == 1


@pytest.mark.asyncio
async def test_add_users_emits_timeline_events_during_ramp() -> None:
    repo = _FakeStateRepo()
    service = _make_service(repo, ["w1"])

    await service.add_users(
        list(range(1, 101)),  # 100 users -> every max(1, 100//50)=2 users emit
        epoch=7,
        spawn_interval_ms=0,
        timeline_source="start_test",
        initial_user_count=0,
    )

    # Expect events at 2, 4, ..., 100 users. 50 events total.
    assert len(repo.timeline) == 50
    assert repo.timeline[0]["users_count"] == 2
    assert repo.timeline[-1] == {"epoch": 7, "users_count": 100, "source": "start_test"}


@pytest.mark.asyncio
async def test_add_users_timeline_respects_initial_count() -> None:
    repo = _FakeStateRepo()
    service = _make_service(repo, ["w1"])

    await service.add_users(
        [101, 102],  # tiny batch, every user emits (max(1, 2//50) == 1)
        epoch=3,
        spawn_interval_ms=0,
        timeline_source="change_users",
        initial_user_count=100,
    )

    assert [evt["users_count"] for evt in repo.timeline] == [101, 102]
    assert repo.timeline[-1]["source"] == "change_users"
