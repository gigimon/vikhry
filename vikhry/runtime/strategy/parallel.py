from __future__ import annotations

import random

from vikhry.runtime.strategy._common import find_ready_steps
from vikhry.runtime.strategy.types import BoundStepT, StepSelection, StepStrategy


class ParallelReadyStrategy[BoundStepT](StepStrategy[BoundStepT]):
    def select(
        self,
        *,
        steps: tuple[BoundStepT, ...],
        completed_steps: set[str],
        next_allowed_at: dict[str, float],
        now: float,
        rng: random.Random,
    ) -> StepSelection[BoundStepT]:
        _ = rng
        ready, nearest_ready_at = find_ready_steps(
            steps=steps,
            completed_steps=completed_steps,
            next_allowed_at=next_allowed_at,
            now=now,
        )
        return StepSelection(steps=tuple(ready), nearest_ready_at=nearest_ready_at)

