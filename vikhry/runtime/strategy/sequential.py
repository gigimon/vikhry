from __future__ import annotations

import random

from vikhry.runtime.strategy._common import find_ready_steps
from vikhry.runtime.strategy.types import BoundStepT, StepSelection, StepStrategy


class SequentialWeightedStrategy[BoundStepT](StepStrategy[BoundStepT]):
    def select(
        self,
        *,
        steps: tuple[BoundStepT, ...],
        completed_steps: set[str],
        next_allowed_at: dict[str, float],
        now: float,
        rng: random.Random,
    ) -> StepSelection[BoundStepT]:
        ready, nearest_ready_at = find_ready_steps(
            steps=steps,
            completed_steps=completed_steps,
            next_allowed_at=next_allowed_at,
            now=now,
        )
        if not ready:
            return StepSelection(steps=(), nearest_ready_at=nearest_ready_at)

        chosen = rng.choices(
            ready,
            weights=[item.spec.weight for item in ready],
            k=1,
        )[0]
        return StepSelection(steps=(chosen,), nearest_ready_at=nearest_ready_at)

