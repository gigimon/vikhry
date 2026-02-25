from __future__ import annotations

import random
from dataclasses import dataclass

from vikhry.runtime.strategy import ParallelReadyStrategy, SequentialWeightedStrategy


@dataclass(slots=True, frozen=True)
class _Spec:
    step_name: str
    weight: float = 1.0
    requires: tuple[str, ...] = ()


@dataclass(slots=True, frozen=True)
class _Step:
    spec: _Spec


def test_sequential_strategy_selects_single_ready_step_spec() -> None:
    strategy = SequentialWeightedStrategy[_Step]()
    steps = (
        _Step(_Spec(step_name="a", weight=1.0)),
        _Step(_Spec(step_name="b", weight=1.0, requires=("a",))),
        _Step(_Spec(step_name="c", weight=1.0)),
    )

    selection = strategy.select(
        steps=steps,
        completed_steps=set(),
        next_allowed_at={"c": 10.0},
        now=5.0,
        rng=random.Random(7),
    )

    assert len(selection.steps) == 1
    assert selection.steps[0].spec.step_name == "a"
    assert selection.nearest_ready_at == 10.0


def test_parallel_strategy_selects_all_ready_steps_spec() -> None:
    strategy = ParallelReadyStrategy[_Step]()
    steps = (
        _Step(_Spec(step_name="a", weight=1.0)),
        _Step(_Spec(step_name="b", weight=1.0)),
        _Step(_Spec(step_name="c", weight=1.0, requires=("a",))),
    )

    selection = strategy.select(
        steps=steps,
        completed_steps=set(),
        next_allowed_at={},
        now=2.0,
        rng=random.Random(3),
    )

    assert [step.spec.step_name for step in selection.steps] == ["a", "b"]
    assert selection.nearest_ready_at is None
