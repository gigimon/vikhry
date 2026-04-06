from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable
from typing import Any

import pytest

from vikhry.runtime import VU, emit_metric, metric, step
from vikhry.runtime.strategy import StepSelection
from vikhry.worker.services.vu_runtime import WorkerVURuntime, load_vu_type


class _FakeRepo:
    def __init__(self) -> None:
        self.metric_events: list[tuple[str, dict[str, Any]]] = []
        self.acquired_resource_names: list[str] = []
        self.released_resources: list[tuple[str, str]] = []
        self.active_users: set[str] = set()

    async def append_metric_event(self, metric_id: str, event: dict[str, Any]) -> str:
        self.metric_events.append((metric_id, event))
        return str(len(self.metric_events))

    async def acquire_resource_data(self, resource_name: str) -> dict[str, Any] | None:
        self.acquired_resource_names.append(resource_name)
        return {"resource_id": "42", "email": "test@example.com"}

    async def release_resource(self, resource_name: str, resource_id: int | str) -> None:
        self.released_resources.append((resource_name, str(resource_id)))

    async def add_worker_active_user(self, _worker_id: str, user_id: int | str) -> None:
        self.active_users.add(str(user_id))

    async def remove_worker_active_user(self, _worker_id: str, user_id: int | str) -> None:
        self.active_users.discard(str(user_id))


async def _wait_until(predicate: Callable[[], bool], timeout_s: float = 1.5) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("condition not met before timeout")


class _MetricsVU(VU):
    started: set[str] = set()
    stopped: set[str] = set()

    async def on_start(self) -> None:
        self.__class__.started.add(self.user_id)
        self.user = await self.resources.acquire("users")

    async def on_stop(self) -> None:
        self.__class__.stopped.add(self.user_id)
        await self.resources.release("users", self.user["resource_id"])

    @step(every_s=0.01)
    async def ping(self) -> None:
        await asyncio.sleep(0)


class _InitParamsVU(VU):
    seen: list[tuple[str, int]] = []

    async def on_init(self, tenant: str, warmup: int = 1) -> None:
        self.__class__.seen.append((tenant, int(warmup)))

    @step(every_s=0.01)
    async def ping(self) -> None:
        await asyncio.sleep(0)


class _OnlyFirstStrategy:
    def select(
        self,
        *,
        steps: tuple[Any, ...],
        completed_steps: set[str],
        next_allowed_at: dict[str, float],
        now: float,
        rng: Any,
    ) -> StepSelection[Any]:
        _ = (completed_steps, next_allowed_at, now, rng)
        if not steps:
            return StepSelection(steps=(), nearest_ready_at=None)
        return StepSelection(steps=(steps[0],), nearest_ready_at=None)


class _CustomStrategyVU(VU):
    step_strategy = _OnlyFirstStrategy

    @step(name="first", every_s=0.01)
    async def first(self) -> None:
        await asyncio.sleep(0)

    @step(name="second", every_s=0.01)
    async def second(self) -> None:
        await asyncio.sleep(0)


class _ManualMetricVU(VU):
    @metric(name="helper_prepare", component="auth")
    async def helper(self) -> None:
        await asyncio.sleep(0)

    @step(every_s=0.01)
    async def ping(self) -> None:
        await self.helper()
        await emit_metric(
            name="/auth",
            status=True,
            time=1.23,
            source="http",
            stage="execute",
            result_code="HTTP_200",
            result_category="ok",
            fatal=False,
            method="POST",
        )
        await asyncio.sleep(0)


class _Status500Response:
    status = 500


class _StatusFailVU(VU):
    @step(every_s=0.01)
    async def ping(self) -> _Status500Response:
        await asyncio.sleep(0)
        return _Status500Response()


class _ExceptionFailVU(VU):
    @step(every_s=0.01)
    async def ping(self) -> None:
        await asyncio.sleep(0)
        raise RuntimeError("boom")


class _InitFailVU(VU):
    step_calls = 0

    async def on_init(self, **_kwargs: Any) -> None:
        raise RuntimeError("init boom")

    @step(every_s=0.01)
    async def ping(self) -> None:
        self.__class__.step_calls += 1
        await asyncio.sleep(0)


class _StartFailVU(VU):
    step_calls = 0

    async def on_start(self) -> None:
        raise RuntimeError("start boom")

    @step(every_s=0.01)
    async def ping(self) -> None:
        self.__class__.step_calls += 1
        await asyncio.sleep(0)


class _StartupJitterProbeVU(VU):
    on_init_started_at: list[float] = []

    async def on_init(self, **_kwargs: Any) -> None:
        self.__class__.on_init_started_at.append(time.monotonic())

    @step(every_s=0.01)
    async def ping(self) -> None:
        await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_runtime_runs_steps_emits_metrics_and_calls_hooks_spec() -> None:
    _MetricsVU.started.clear()
    _MetricsVU.stopped.clear()
    repo = _FakeRepo()
    runtime = WorkerVURuntime(
        repo,  # type: ignore[arg-type]
        worker_id="w1",
        vu_type=_MetricsVU,
        idle_sleep_s=0.01,
    )

    task = asyncio.create_task(runtime.run_user("user-1"))
    await _wait_until(lambda: len(repo.metric_events) >= 2)
    assert "user-1" in repo.active_users
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)

    assert "user-1" in _MetricsVU.started
    assert "user-1" in _MetricsVU.stopped
    assert "user-1" not in repo.active_users
    assert repo.acquired_resource_names == ["users"]
    assert repo.released_resources == [("users", "42")]
    assert all(metric_id == "ping" for metric_id, _ in repo.metric_events)
    first_event = repo.metric_events[0][1]
    assert first_event["worker_id"] == "w1"
    assert first_event["user_id"] == "user-1"
    assert first_event["name"] == "ping"
    assert first_event["step"] == "ping"
    assert first_event["status"] is True
    assert first_event["source"] == "step"
    assert first_event["stage"] == "execute"
    assert first_event["result_code"] == "STEP_OK"
    assert first_event["result_category"] == "ok"
    assert first_event["fatal"] is False
    assert "time" in first_event
    assert "error_message" not in first_event
    assert "traceback" not in first_event


def test_load_vu_type_resolves_valid_path_spec() -> None:
    vu_type = load_vu_type("vikhry.runtime.defaults:IdleVU")
    assert issubclass(vu_type, VU)


def test_load_vu_type_rejects_invalid_path_spec() -> None:
    with pytest.raises(ValueError, match="module.path:ClassName"):
        load_vu_type("invalid-path")


@pytest.mark.asyncio
async def test_runtime_passes_init_params_to_on_init_spec() -> None:
    _InitParamsVU.seen.clear()
    repo = _FakeRepo()
    runtime = WorkerVURuntime(
        repo,  # type: ignore[arg-type]
        worker_id="w1",
        vu_type=_InitParamsVU,
        idle_sleep_s=0.01,
    )

    task = asyncio.create_task(
        runtime.run_user("user-1", {"tenant": "acme", "warmup": 2})
    )
    await _wait_until(lambda: len(repo.metric_events) >= 1)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)

    assert _InitParamsVU.seen == [("acme", 2)]


@pytest.mark.asyncio
async def test_runtime_uses_custom_step_strategy_from_vu_spec() -> None:
    repo = _FakeRepo()
    runtime = WorkerVURuntime(
        repo,  # type: ignore[arg-type]
        worker_id="w1",
        vu_type=_CustomStrategyVU,
        idle_sleep_s=0.01,
    )

    task = asyncio.create_task(runtime.run_user("user-1"))
    await _wait_until(lambda: len(repo.metric_events) >= 3)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)

    assert all(event["step"] == "first" for _, event in repo.metric_events)


@pytest.mark.asyncio
async def test_runtime_supports_manual_and_decorator_metrics_spec() -> None:
    repo = _FakeRepo()
    runtime = WorkerVURuntime(
        repo,  # type: ignore[arg-type]
        worker_id="w1",
        vu_type=_ManualMetricVU,
        idle_sleep_s=0.01,
    )

    task = asyncio.create_task(runtime.run_user("user-1"))
    await _wait_until(
        lambda: {
            event["name"] for _, event in repo.metric_events
        }
        >= {"ping", "helper_prepare", "/auth"}
    )
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)

    by_name = {event["name"]: event for _, event in repo.metric_events}
    assert {metric_id for metric_id, _ in repo.metric_events} >= {"ping", "helper_prepare", "/auth"}
    assert all(metric_id == event["name"] for metric_id, event in repo.metric_events)
    assert by_name["/auth"]["step"] == "ping"
    assert by_name["/auth"]["status"] is True
    assert by_name["/auth"]["source"] == "http"
    assert by_name["/auth"]["result_code"] == "HTTP_200"
    assert by_name["/auth"]["method"] == "POST"
    assert by_name["helper_prepare"]["component"] == "auth"


@pytest.mark.asyncio
async def test_runtime_ignores_step_result_status_like_field_spec(
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.WARNING)
    repo = _FakeRepo()
    runtime = WorkerVURuntime(
        repo,  # type: ignore[arg-type]
        worker_id="w1",
        vu_type=_StatusFailVU,
        idle_sleep_s=0.01,
    )

    task = asyncio.create_task(runtime.run_user("user-1"))
    await _wait_until(lambda: len(repo.metric_events) >= 1)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)

    first_event = repo.metric_events[0][1]
    assert first_event["name"] == "ping"
    assert first_event["status"] is True
    assert first_event["result_code"] == "STEP_OK"
    assert "error_message" not in first_event
    assert "traceback" not in first_event
    assert not any("returned error status" in record.getMessage() for record in caplog.records)


@pytest.mark.asyncio
async def test_runtime_logs_error_for_step_exception_spec(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.ERROR)
    repo = _FakeRepo()
    runtime = WorkerVURuntime(
        repo,  # type: ignore[arg-type]
        worker_id="w1",
        vu_type=_ExceptionFailVU,
        idle_sleep_s=0.01,
    )

    task = asyncio.create_task(runtime.run_user("user-1"))
    await _wait_until(lambda: len(repo.metric_events) >= 1)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)

    assert any("raised exception" in record.getMessage() for record in caplog.records)
    assert any(
        event["result_code"] == "STEP_EXCEPTION" and event["status"] is False
        for _, event in repo.metric_events
    )
    assert any(
        "Traceback (most recent call last):" in str(event.get("traceback"))
        and "RuntimeError" in str(event.get("traceback"))
        for _, event in repo.metric_events
        if event["result_code"] == "STEP_EXCEPTION"
    )


@pytest.mark.asyncio
async def test_runtime_does_not_run_steps_when_on_init_fails_spec() -> None:
    _InitFailVU.step_calls = 0
    repo = _FakeRepo()
    runtime = WorkerVURuntime(
        repo,  # type: ignore[arg-type]
        worker_id="w1",
        vu_type=_InitFailVU,
        idle_sleep_s=0.01,
    )

    with pytest.raises(RuntimeError, match="init boom"):
        await runtime.run_user("user-1")

    assert _InitFailVU.step_calls == 0
    assert len(repo.metric_events) == 1
    metric_id, event = repo.metric_events[0]
    assert metric_id == "lifecycle/on_init"
    assert event["source"] == "lifecycle"
    assert event["stage"] == "on_init"
    assert event["result_code"] == "LIFECYCLE_EXCEPTION"
    assert event["result_category"] == "exception"
    assert event["fatal"] is True
    assert "Traceback (most recent call last):" in str(event["traceback"])
    assert "RuntimeError: init boom" in str(event["traceback"])
    assert repo.active_users == set()


@pytest.mark.asyncio
async def test_runtime_does_not_run_steps_when_on_start_fails_spec() -> None:
    _StartFailVU.step_calls = 0
    repo = _FakeRepo()
    runtime = WorkerVURuntime(
        repo,  # type: ignore[arg-type]
        worker_id="w1",
        vu_type=_StartFailVU,
        idle_sleep_s=0.01,
    )

    with pytest.raises(RuntimeError, match="start boom"):
        await runtime.run_user("user-1")

    assert _StartFailVU.step_calls == 0
    assert len(repo.metric_events) == 1
    metric_id, event = repo.metric_events[0]
    assert metric_id == "lifecycle/on_start"
    assert event["source"] == "lifecycle"
    assert event["stage"] == "on_start"
    assert event["result_code"] == "LIFECYCLE_EXCEPTION"
    assert event["result_category"] == "exception"
    assert event["fatal"] is True
    assert "Traceback (most recent call last):" in str(event["traceback"])
    assert "RuntimeError: start boom" in str(event["traceback"])
    assert repo.active_users == set()


@pytest.mark.asyncio
async def test_runtime_applies_startup_jitter_before_on_init_spec() -> None:
    _StartupJitterProbeVU.on_init_started_at.clear()
    repo = _FakeRepo()
    runtime = WorkerVURuntime(
        repo,  # type: ignore[arg-type]
        worker_id="w1",
        vu_type=_StartupJitterProbeVU,
        idle_sleep_s=0.01,
        startup_jitter_s=0.03,
    )

    started_at = time.monotonic()
    task = asyncio.create_task(runtime.run_user("user-1"))
    await _wait_until(lambda: bool(_StartupJitterProbeVU.on_init_started_at))
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)

    elapsed_s = _StartupJitterProbeVU.on_init_started_at[0] - started_at
    assert elapsed_s >= 0.01
