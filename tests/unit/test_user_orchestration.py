from __future__ import annotations

from vikhry.orchestrator.services.user_orchestration import allocate_round_robin


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

