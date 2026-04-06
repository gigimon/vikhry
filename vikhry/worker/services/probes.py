from __future__ import annotations

import asyncio
import importlib
import inspect
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, TypeAlias

from vikhry.runtime import ProbeContext, ProbeSpec, VU, collect_probe_specs, resolve_every_delay
from vikhry.runtime.metrics import exception_fields
from vikhry.worker.models.state import WorkerPhase, WorkerRuntimeState
from vikhry.worker.redis_repo.state_repo import WorkerStateRepository

logger = logging.getLogger(__name__)

DEFAULT_SCENARIO_IMPORT = "vikhry.runtime.defaults:IdleVU"
ProbeValue: TypeAlias = str | int | float | bool | None


@dataclass(slots=True, frozen=True)
class LoadedProbe:
    spec: ProbeSpec
    call: Callable[..., Awaitable[Any]]
    accepts_ctx: bool = False


class WorkerProbePublisher:
    def __init__(
        self,
        state_repo: WorkerStateRepository,
        *,
        worker_id: str,
    ) -> None:
        self._state_repo = state_repo
        self._worker_id = worker_id

    async def register_probe(self, probe_name: str) -> None:
        await self._state_repo.register_probe_name(probe_name)

    async def emit_probe(
        self,
        *,
        probe_name: str,
        status: bool,
        elapsed_ms: float,
        value: ProbeValue,
        error_type: str | None = None,
        error_message: str | None = None,
    ) -> None:
        payload: dict[str, Any] = {
            "name": probe_name,
            "worker_id": self._worker_id,
            "ts_ms": int(time.time() * 1000),
            "status": bool(status),
            "time": round(elapsed_ms, 3),
            "value": value,
        }
        if error_type is not None:
            payload["error_type"] = error_type
        if error_message is not None:
            payload["error_message"] = error_message

        try:
            await self._state_repo.append_probe_event(probe_name, payload)
        except Exception:  # noqa: BLE001
            logger.exception(
                "failed to publish probe event (worker_id=%s, probe=%s)",
                self._worker_id,
                probe_name,
            )


class WorkerProbeRuntime:
    def __init__(
        self,
        state_repo: WorkerStateRepository,
        *,
        runtime_state: WorkerRuntimeState,
        worker_id: str,
        probes: tuple[LoadedProbe, ...],
        idle_sleep_s: float = 0.1,
    ) -> None:
        self._runtime_state = runtime_state
        self._worker_id = worker_id
        self._probes = probes
        self._idle_sleep_s = max(0.01, idle_sleep_s)
        self._publisher = WorkerProbePublisher(state_repo, worker_id=worker_id)
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._stop_event = asyncio.Event()

    async def start(self) -> None:
        if not self._probes:
            return
        if self._tasks:
            return

        self._stop_event = asyncio.Event()
        for probe in self._probes:
            await self._publisher.register_probe(probe.spec.name)
            task = asyncio.create_task(
                self._run_probe_loop(probe),
                name=f"worker-probe:{self._worker_id}:{probe.spec.name}",
            )
            self._tasks[probe.spec.name] = task

    async def stop(self) -> None:
        if not self._tasks:
            return

        self._stop_event.set()
        tasks = list(self._tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()

    async def _run_probe_loop(self, probe: LoadedProbe) -> None:
        try:
            while not self._stop_event.is_set():
                if self._runtime_state.phase is not WorkerPhase.RUNNING:
                    if await self._sleep_or_stop(self._idle_sleep_s):
                        return
                    continue

                await self._execute_probe(probe)

                try:
                    delay_s = resolve_every_delay(probe.spec.every_s)
                except Exception:  # noqa: BLE001
                    logger.warning(
                        "invalid every_s for probe, fallback to idle sleep "
                        "(worker_id=%s, probe=%s)",
                        self._worker_id,
                        probe.spec.name,
                        exc_info=True,
                    )
                    delay_s = self._idle_sleep_s
                if await self._sleep_or_stop(delay_s):
                    return
        except asyncio.CancelledError:
            raise

    async def _execute_probe(self, probe: LoadedProbe) -> None:
        started_at = time.perf_counter()
        success = False
        value: ProbeValue = None
        error_type: str | None = None
        error_message: str | None = None

        try:
            result = await self._call_probe(probe)
            value = _normalize_probe_value(result)
            success = True
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            error_payload = exception_fields(exc)
            error_type = error_payload["error_type"]
            error_message = error_payload["error_message"]
            logger.exception(
                "probe execution failed (worker_id=%s, probe=%s)",
                self._worker_id,
                probe.spec.name,
            )

        await self._publisher.emit_probe(
            probe_name=probe.spec.name,
            status=success,
            elapsed_ms=(time.perf_counter() - started_at) * 1000,
            value=value,
            error_type=error_type,
            error_message=error_message,
        )

    def _build_probe_context(self) -> ProbeContext:
        return ProbeContext(init_params=dict(self._runtime_state.init_params))

    async def _call_probe(self, probe: LoadedProbe) -> Any:
        args: tuple[Any, ...] = ()
        if probe.accepts_ctx:
            args = (self._build_probe_context(),)
        if probe.spec.timeout is None:
            return await probe.call(*args)
        async with asyncio.timeout(probe.spec.timeout):
            return await probe.call(*args)

    async def _sleep_or_stop(self, delay_s: float) -> bool:
        if delay_s <= 0:
            await asyncio.sleep(0)
            return self._stop_event.is_set()
        try:
            await asyncio.wait_for(self._stop_event.wait(), timeout=delay_s)
        except TimeoutError:
            return False
        return True


def load_probe_targets(import_path: str) -> tuple[LoadedProbe, ...]:
    module, _vu_type = _load_scenario_module_and_vu_type(import_path)
    probes: list[LoadedProbe] = []
    for spec in collect_probe_specs(module.__dict__):
        target = getattr(module, spec.function_name, None)
        if not inspect.iscoroutinefunction(target):
            raise TypeError(f"probe target `{spec.function_name}` must be an async function")
        accepts_ctx = _probe_accepts_ctx(target)
        probes.append(LoadedProbe(spec=spec, call=target, accepts_ctx=accepts_ctx))
    return tuple(probes)


def _probe_accepts_ctx(func: Callable[..., Any]) -> bool:
    try:
        sig = inspect.signature(func)
        params = list(sig.parameters.values())
        if not params:
            return False
        first = params[0]
        return first.kind in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        )
    except (ValueError, TypeError):
        return False


def _load_scenario_module_and_vu_type(import_path: str) -> tuple[Any, type[VU]]:
    normalized = (import_path or "").strip()
    if not normalized:
        normalized = DEFAULT_SCENARIO_IMPORT

    module_name, sep, attr_name = normalized.partition(":")
    if not sep or not module_name or not attr_name:
        raise ValueError("scenario import path must use format `module.path:ClassName`")

    module = importlib.import_module(module_name)
    candidate = getattr(module, attr_name, None)
    if candidate is None:
        raise ValueError(f"scenario class `{attr_name}` not found in module `{module_name}`")
    if not inspect.isclass(candidate):
        raise ValueError(f"scenario target `{normalized}` must be a class")
    if not issubclass(candidate, VU):
        raise ValueError(f"scenario class `{normalized}` must inherit from VU")
    return module, candidate


def _normalize_probe_value(value: Any) -> ProbeValue:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    raise TypeError("probe value must be a scalar")
