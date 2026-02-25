from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from typing import Any

import pytest

from vikhry.runtime import VU, step
from vikhry.worker.services.vu_runtime import WorkerVURuntime, load_vu_type


class _FakeRepo:
    def __init__(self) -> None:
        self.metric_events: list[tuple[str, dict[str, Any]]] = []
        self.acquired_resource_names: list[str] = []
        self.released_resources: list[tuple[str, str]] = []

    async def append_metric_event(self, metric_id: str, event: dict[str, Any]) -> str:
        self.metric_events.append((metric_id, event))
        return str(len(self.metric_events))

    async def acquire_resource_data(self, resource_name: str) -> dict[str, Any] | None:
        self.acquired_resource_names.append(resource_name)
        return {"resource_id": "42", "email": "test@example.com"}

    async def release_resource(self, resource_name: str, resource_id: int | str) -> None:
        self.released_resources.append((resource_name, str(resource_id)))


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
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)

    assert "user-1" in _MetricsVU.started
    assert "user-1" in _MetricsVU.stopped
    assert repo.acquired_resource_names == ["users"]
    assert repo.released_resources == [("users", "42")]
    assert all(metric_id == "worker:w1" for metric_id, _ in repo.metric_events)
    first_event = repo.metric_events[0][1]
    assert first_event["worker_id"] == "w1"
    assert first_event["user_id"] == "user-1"
    assert first_event["step"] == "ping"
    assert "latency_ms" in first_event
    assert "error" not in first_event


def test_load_vu_type_resolves_valid_path_spec() -> None:
    vu_type = load_vu_type("vikhry.runtime.defaults:IdleVU")
    assert issubclass(vu_type, VU)


def test_load_vu_type_rejects_invalid_path_spec() -> None:
    with pytest.raises(ValueError, match="module.path:ClassName"):
        load_vu_type("invalid-path")
