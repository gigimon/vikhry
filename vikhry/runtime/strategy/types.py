from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Protocol, TypeVar, runtime_checkable


class StepSpecLike(Protocol):
    step_name: str
    weight: float
    requires: tuple[str, ...]
    strategy_kwargs: dict[str, object]


class BoundStepLike(Protocol):
    spec: StepSpecLike


BoundStepT = TypeVar("BoundStepT", bound=BoundStepLike)


@dataclass(slots=True, frozen=True)
class StepSelection[BoundStepT]:
    steps: tuple[BoundStepT, ...]
    nearest_ready_at: float | None = None


@runtime_checkable
class StepStrategy(Protocol[BoundStepT]):
    def select(
        self,
        *,
        steps: tuple[BoundStepT, ...],
        completed_steps: set[str],
        next_allowed_at: dict[str, float],
        now: float,
        rng: random.Random,
    ) -> StepSelection[BoundStepT]:
        """Choose which ready steps should run now."""
