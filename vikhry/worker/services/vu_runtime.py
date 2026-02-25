from __future__ import annotations

import asyncio
import importlib
import inspect
import logging
import random
import time
from typing import Any

from vikhry.runtime import VU, bind_steps, resolve_every_delay
from vikhry.runtime.strategy import SequentialWeightedStrategy, StepStrategy
from vikhry.worker.redis_repo.state_repo import WorkerStateRepository
from vikhry.worker.services.resources import WorkerVUResources

logger = logging.getLogger(__name__)

DEFAULT_SCENARIO_IMPORT = "vikhry.runtime.defaults:IdleVU"


class WorkerVURuntime:
    def __init__(
        self,
        state_repo: WorkerStateRepository,
        *,
        worker_id: str,
        vu_type: type[VU],
        http_base_url: str = "",
        metric_id: str | None = None,
        idle_sleep_s: float = 0.05,
    ) -> None:
        self._state_repo = state_repo
        self._worker_id = worker_id
        self._vu_type = vu_type
        self._http_base_url = http_base_url
        self._metric_id = metric_id or f"worker:{worker_id}"
        self._idle_sleep_s = max(0.01, idle_sleep_s)

    async def run_user(
        self,
        user_id: str,
        init_params: dict[str, Any] | None = None,
    ) -> None:
        resources = WorkerVUResources(self._state_repo)
        vu = self._vu_type(
            user_id=user_id,
            worker_id=self._worker_id,
            resources=resources,
            http_base_url=self._http_base_url,
        )
        init_kwargs = dict(init_params or {})

        completed_steps: set[str] = set()
        next_allowed_at: dict[str, float] = {}
        rng = random.Random(f"{self._worker_id}:{user_id}")
        steps = bind_steps(vu)
        step_strategy = _resolve_step_strategy(vu.step_strategy)

        try:
            if init_kwargs:
                await vu.on_init(**init_kwargs)
            else:
                await vu.on_init()
            vu.ensure_http_client()
            await vu.on_start()
            while True:
                now = time.monotonic()
                selection = step_strategy.select(
                    steps=steps,
                    completed_steps=completed_steps,
                    next_allowed_at=next_allowed_at,
                    now=now,
                    rng=rng,
                )

                if not selection.steps:
                    if selection.nearest_ready_at is None:
                        await asyncio.sleep(self._idle_sleep_s)
                    else:
                        await asyncio.sleep(
                            max(self._idle_sleep_s, selection.nearest_ready_at - now)
                        )
                    continue

                if len(selection.steps) == 1:
                    await self._execute_step(
                        user_id=user_id,
                        completed_steps=completed_steps,
                        next_allowed_at=next_allowed_at,
                        bound_step=selection.steps[0],
                    )
                    continue

                await asyncio.gather(
                    *(
                        self._execute_step(
                            user_id=user_id,
                            completed_steps=completed_steps,
                            next_allowed_at=next_allowed_at,
                            bound_step=bound_step,
                        )
                        for bound_step in selection.steps
                    )
                )
        except asyncio.CancelledError:
            raise
        finally:
            try:
                await vu.on_stop()
            finally:
                await vu.close()

    async def _execute_step(
        self,
        *,
        user_id: str,
        completed_steps: set[str],
        next_allowed_at: dict[str, float],
        bound_step: Any,
    ) -> None:
        spec = bound_step.spec
        started_at = time.perf_counter()
        status_code: int | None = None
        error_text: str | None = None
        success = False
        cancelled = False

        try:
            if spec.timeout is None:
                result = await bound_step.call()
            else:
                async with asyncio.timeout(spec.timeout):
                    result = await bound_step.call()
            status_code = _extract_status_code(result)
            success = status_code is None or status_code < 400
            if success:
                completed_steps.add(spec.step_name)
            else:
                error_text = f"http_status_{status_code}"
        except asyncio.CancelledError:
            cancelled = True
            raise
        except Exception as exc:  # noqa: BLE001
            error_text = f"{type(exc).__name__}: {exc}"
            logger.debug(
                "VU step failed (worker_id=%s, user_id=%s, step=%s)",
                self._worker_id,
                user_id,
                spec.step_name,
                exc_info=True,
            )
        finally:
            elapsed_ms = round((time.perf_counter() - started_at) * 1000, 3)
            try:
                every_delay = resolve_every_delay(spec.every_s)
            except Exception:  # noqa: BLE001
                logger.warning(
                    "invalid every_s for step, fallback to immediate scheduling "
                    "(worker_id=%s, step=%s)",
                    self._worker_id,
                    spec.step_name,
                    exc_info=True,
                )
                every_delay = 0.0
            next_allowed_at[spec.step_name] = time.monotonic() + every_delay if every_delay > 0 else 0.0
            if not cancelled:
                event = {
                    "ts_ms": int(time.time() * 1000),
                    "worker_id": self._worker_id,
                    "user_id": user_id,
                    "step": spec.step_name,
                    "latency_ms": elapsed_ms,
                }
                if status_code is not None:
                    event["status_code"] = status_code
                if not success:
                    event["error"] = error_text or "step_error"
                await self._publish_metric_event(event)

    async def _publish_metric_event(self, event: dict[str, Any]) -> None:
        try:
            await self._state_repo.append_metric_event(self._metric_id, event)
        except Exception:  # noqa: BLE001
            logger.exception(
                "failed to publish worker metric (worker_id=%s, metric_id=%s)",
                self._worker_id,
                self._metric_id,
            )


def _resolve_step_strategy(candidate: object) -> StepStrategy[Any]:
    if candidate is None:
        return SequentialWeightedStrategy()
    if isinstance(candidate, type):
        candidate = candidate()
    if not isinstance(candidate, StepStrategy):
        raise TypeError("VU step_strategy must implement select(...)")
    return candidate


def load_vu_type(import_path: str) -> type[VU]:
    normalized = (import_path or "").strip()
    if not normalized:
        normalized = DEFAULT_SCENARIO_IMPORT

    module_name, sep, attr_name = normalized.partition(":")
    if not sep or not module_name or not attr_name:
        raise ValueError(
            "scenario import path must use format `module.path:ClassName`"
        )

    module = importlib.import_module(module_name)
    candidate = getattr(module, attr_name, None)
    if candidate is None:
        raise ValueError(f"scenario class `{attr_name}` not found in module `{module_name}`")
    if not inspect.isclass(candidate):
        raise ValueError(f"scenario target `{normalized}` must be a class")
    if not issubclass(candidate, VU):
        raise ValueError(f"scenario class `{normalized}` must inherit from VU")
    return candidate


def _extract_status_code(result: Any) -> int | None:
    status = getattr(result, "status", None)
    if status is None:
        return None
    try:
        return int(status)
    except (TypeError, ValueError):
        return None
