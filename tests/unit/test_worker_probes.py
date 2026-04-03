from __future__ import annotations

import asyncio
import time
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from vikhry.runtime import ProbeSpec, VU, probe
from vikhry.worker.models.state import WorkerPhase, WorkerRuntimeState
from vikhry.worker.services.probes import LoadedProbe, WorkerProbeRuntime, load_probe_targets


class _FakeProbeRepo:
    def __init__(self) -> None:
        self.registered_probes: list[str] = []
        self.probe_events: list[tuple[str, dict[str, Any]]] = []

    async def register_probe_name(self, probe_name: str) -> None:
        self.registered_probes.append(probe_name)

    async def append_probe_event(self, probe_name: str, event: dict[str, Any]) -> str:
        self.probe_events.append((probe_name, event))
        return str(len(self.probe_events))


async def _wait_until(
    predicate: Callable[[], bool],
    *,
    timeout_s: float = 1.5,
    poll_interval_s: float = 0.01,
) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return
        await asyncio.sleep(poll_interval_s)
    raise AssertionError("condition not met before timeout")


class _ProbeCounters:
    fast_calls = 0
    slow_calls = 0


@probe(name="fast_probe", every_s=0.01)
async def _fast_probe() -> int:
    _ProbeCounters.fast_calls += 1
    return _ProbeCounters.fast_calls


@probe(name="slow_probe", every_s=0.03)
async def _slow_probe() -> int:
    _ProbeCounters.slow_calls += 1
    return _ProbeCounters.slow_calls


@probe(name="timeout_probe", every_s=0.01, timeout=0.01)
async def _timeout_probe() -> int:
    await asyncio.Event().wait()
    return 0


@probe(name="bad_value_probe", every_s=0.01)
async def _bad_value_probe() -> dict[str, str]:
    return {"bad": "value"}


@probe(name="boom_probe", every_s=0.01)
async def _boom_probe() -> int:
    raise RuntimeError("boom")


def _loaded_probe(
    *,
    name: str,
    function_name: str,
    every_s: float,
    call: Callable[[], Any],
    timeout: float | None = None,
) -> LoadedProbe:
    return LoadedProbe(
        spec=ProbeSpec(
            name=name,
            function_name=function_name,
            every_s=every_s,
            timeout=timeout,
        ),
        call=call,
    )


@pytest.mark.asyncio
async def test_probe_runtime_runs_independent_probe_loops_only_while_running_spec() -> None:
    _ProbeCounters.fast_calls = 0
    _ProbeCounters.slow_calls = 0
    repo = _FakeProbeRepo()
    state = WorkerRuntimeState()
    runtime = WorkerProbeRuntime(
        repo,  # type: ignore[arg-type]
        runtime_state=state,
        worker_id="w1",
        probes=(
            _loaded_probe(
                name="fast_probe",
                function_name="_fast_probe",
                every_s=0.01,
                call=_fast_probe,
            ),
            _loaded_probe(
                name="slow_probe",
                function_name="_slow_probe",
                every_s=0.03,
                call=_slow_probe,
            ),
        ),
        idle_sleep_s=0.01,
    )

    await runtime.start()
    try:
        await asyncio.sleep(0.05)
        assert repo.probe_events == []
        assert repo.registered_probes == ["fast_probe", "slow_probe"]

        state.phase = WorkerPhase.RUNNING
        await _wait_until(
            lambda: Counter(name for name, _ in repo.probe_events)["fast_probe"] >= 3
            and Counter(name for name, _ in repo.probe_events)["slow_probe"] >= 1
        )

        counts = Counter(name for name, _ in repo.probe_events)
        assert counts["fast_probe"] > counts["slow_probe"]
        assert all(event["worker_id"] == "w1" for _, event in repo.probe_events)
    finally:
        await runtime.stop()


@pytest.mark.asyncio
async def test_probe_runtime_emits_timeout_error_event_spec() -> None:
    repo = _FakeProbeRepo()
    state = WorkerRuntimeState(phase=WorkerPhase.RUNNING)
    runtime = WorkerProbeRuntime(
        repo,  # type: ignore[arg-type]
        runtime_state=state,
        worker_id="w-timeout",
        probes=(
            _loaded_probe(
                name="timeout_probe",
                function_name="_timeout_probe",
                every_s=0.01,
                timeout=0.01,
                call=_timeout_probe,
            ),
        ),
        idle_sleep_s=0.01,
    )

    await runtime.start()
    try:
        await _wait_until(lambda: len(repo.probe_events) >= 1)
        event = repo.probe_events[0][1]
        assert event["name"] == "timeout_probe"
        assert event["status"] is False
        assert event["value"] is None
        assert event["error_type"] == "TimeoutError"
        assert "time" in event
    finally:
        await runtime.stop()


@pytest.mark.asyncio
async def test_probe_runtime_treats_invalid_probe_value_as_probe_failure_spec() -> None:
    repo = _FakeProbeRepo()
    state = WorkerRuntimeState(phase=WorkerPhase.RUNNING)
    runtime = WorkerProbeRuntime(
        repo,  # type: ignore[arg-type]
        runtime_state=state,
        worker_id="w-bad-value",
        probes=(
            _loaded_probe(
                name="bad_value_probe",
                function_name="_bad_value_probe",
                every_s=0.01,
                call=_bad_value_probe,
            ),
        ),
        idle_sleep_s=0.01,
    )

    await runtime.start()
    try:
        await _wait_until(lambda: len(repo.probe_events) >= 1)
        event = repo.probe_events[0][1]
        assert event["name"] == "bad_value_probe"
        assert event["status"] is False
        assert event["error_type"] == "TypeError"
        assert "scalar" in event["error_message"]
    finally:
        await runtime.stop()


@pytest.mark.asyncio
async def test_probe_runtime_keeps_running_after_probe_exception_spec() -> None:
    repo = _FakeProbeRepo()
    state = WorkerRuntimeState(phase=WorkerPhase.RUNNING)
    runtime = WorkerProbeRuntime(
        repo,  # type: ignore[arg-type]
        runtime_state=state,
        worker_id="w-boom",
        probes=(
            _loaded_probe(
                name="boom_probe",
                function_name="_boom_probe",
                every_s=0.01,
                call=_boom_probe,
            ),
        ),
        idle_sleep_s=0.01,
    )

    await runtime.start()
    try:
        await _wait_until(lambda: len(repo.probe_events) >= 2)
        assert all(event["status"] is False for _, event in repo.probe_events[:2])
        assert all(event["error_type"] == "RuntimeError" for _, event in repo.probe_events[:2])
    finally:
        await runtime.stop()


def test_load_probe_targets_extracts_module_level_probes_from_import_path_spec(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    package = tmp_path / "tmp_probe_runtime" / "scenarios"
    package.mkdir(parents=True, exist_ok=True)
    (tmp_path / "tmp_probe_runtime" / "__init__.py").write_text("", encoding="utf-8")
    (package / "__init__.py").write_text("", encoding="utf-8")
    scenario = package / "scenario.py"
    scenario.write_text(
        """
from vikhry import VU, probe

@probe(name="db_health", every_s=1.0)
async def poll_db():
    return 1

@probe(name="cache_health", every_s=2.0, timeout=0.5)
async def poll_cache():
    return 2

class ProbeVU(VU):
    pass
""".strip(),
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))

    probes = load_probe_targets("tmp_probe_runtime.scenarios.scenario:ProbeVU")
    assert [probe.spec.name for probe in probes] == ["db_health", "cache_health"]
    assert [probe.spec.function_name for probe in probes] == ["poll_db", "poll_cache"]


def test_load_probe_targets_rejects_invalid_import_path_spec() -> None:
    with pytest.raises(ValueError, match="module.path:ClassName"):
        load_probe_targets("bad-path")


class _NoopVU(VU):
    pass
