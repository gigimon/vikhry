from __future__ import annotations

from vikhry.runtime.strategy.types import BoundStepT


def find_ready_steps(
    *,
    steps: tuple[BoundStepT, ...],
    completed_steps: set[str],
    next_allowed_at: dict[str, float],
    now: float,
) -> tuple[list[BoundStepT], float | None]:
    ready: list[BoundStepT] = []
    nearest_ready_at: float | None = None

    for bound_step in steps:
        spec = bound_step.spec
        if any(required not in completed_steps for required in spec.requires):
            continue
        ready_at = next_allowed_at.get(spec.step_name, 0.0)
        if ready_at <= now:
            ready.append(bound_step)
            continue
        if nearest_ready_at is None or ready_at < nearest_ready_at:
            nearest_ready_at = ready_at

    return ready, nearest_ready_at

