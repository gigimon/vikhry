from __future__ import annotations

from typing import Any

import pytest

from vikhry.orchestrator.services.probe_service import ProbeService


class _FakeStateRepo:
    def __init__(self, events_by_probe: dict[str, list[dict[str, Any]]]) -> None:
        self._events_by_probe = {
            probe_name: list(events) for probe_name, events in events_by_probe.items()
        }
        self.probes_cleared = False

    async def list_probes(self) -> list[str]:
        return sorted(self._events_by_probe)

    async def read_probe_events_after(
        self,
        probe_name: str,
        after_event_id: str | None,
        count: int = 100,
    ) -> list[dict[str, Any]]:
        events = self._events_by_probe.get(probe_name, [])
        if after_event_id is None:
            start_index = 0
        else:
            start_index = 0
            for index, event in enumerate(events):
                if event["event_id"] == after_event_id:
                    start_index = index + 1
                    break
            else:
                start_index = len(events)
        return events[start_index : start_index + count]

    async def clear_probe_data(self) -> int:
        keys = len(self._events_by_probe) + 1
        self.probes_cleared = True
        self._events_by_probe.clear()
        return keys


class _FailingListProbesRepo:
    async def list_probes(self) -> list[str]:
        raise RuntimeError("boom")


def _probe_events(
    statuses: list[bool],
    values: list[object],
    *,
    start_ts_ms: int = 1_700_000_000_000,
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for index, (status, value) in enumerate(zip(statuses, values, strict=True)):
        ts_ms = start_ts_ms + index
        payload: dict[str, Any] = {
            "ts_ms": ts_ms,
            "status": status,
            "time": 1.5 + index,
            "value": value,
        }
        if not status:
            payload["error_type"] = "RuntimeError"
            payload["error_message"] = "boom"
        events.append({"event_id": f"{ts_ms}-{index}", "data": payload})
    return events


@pytest.mark.asyncio
async def test_probe_service_aggregates_latest_counters_and_recent_events_spec() -> None:
    repo = _FakeStateRepo(
        {
            "db_health": _probe_events(
                [True, False, True],
                [1, None, 2],
            )
        }
    )
    service = ProbeService(
        state_repo=repo,  # type: ignore[arg-type]
        window_s=60,
        max_recent_events_per_probe=10,
    )

    await service.refresh_now()
    snapshot = await service.get_probes(probe_name="db_health", include_events=True)

    probe = snapshot["probes"][0]
    assert probe["probe_name"] == "db_health"
    assert probe["last_event_id"] == "1700000000002-2"
    assert probe["aggregate"] == {
        "window_s": 60,
        "successes": 2,
        "errors": 1,
        "last_ts_ms": 1_700_000_000_002,
        "last_status": True,
        "last_value": 2,
    }
    assert probe["latest"] == {
        "ts_ms": 1_700_000_000_002,
        "status": True,
        "value": 2,
        "time": 3.5,
        "error_type": None,
        "error_message": None,
    }
    assert len(probe["events"]) == 3


@pytest.mark.asyncio
async def test_probe_service_includes_declared_probe_names_without_events_spec() -> None:
    service = ProbeService(
        state_repo=_FakeStateRepo({}),  # type: ignore[arg-type]
        declared_probe_names=["db_health"],
        window_s=60,
    )

    snapshot = await service.get_probes(include_events=False)

    assert snapshot["probes"] == [
        {
            "probe_name": "db_health",
            "last_event_id": None,
            "aggregate": {
                "window_s": 60,
                "successes": 0,
                "errors": 0,
                "last_ts_ms": None,
                "last_status": None,
                "last_value": None,
            },
            "latest": None,
            "events": None,
        }
    ]


@pytest.mark.asyncio
async def test_probe_service_history_returns_only_requested_probe_events_spec() -> None:
    repo = _FakeStateRepo(
        {
            "db_health": _probe_events([True, False, True], [1, None, 2]),
            "cache_health": _probe_events([True], [10]),
        }
    )
    service = ProbeService(
        state_repo=repo,  # type: ignore[arg-type]
        window_s=60,
    )

    await service.refresh_now()
    history = await service.get_probe_history(probe_name="db_health", count=2)

    assert history["probe_name"] == "db_health"
    assert history["count"] == 2
    assert history["last_event_id"] == "1700000000002-2"
    assert [event["data"]["value"] for event in history["events"]] == [None, 2]


@pytest.mark.asyncio
async def test_probe_service_reset_for_new_run_clears_redis_and_in_memory_state_spec() -> None:
    repo = _FakeStateRepo({"db_health": _probe_events([True], [1])})
    service = ProbeService(
        state_repo=repo,  # type: ignore[arg-type]
        window_s=60,
    )

    await service.refresh_now()
    before = await service.get_probes(include_events=False)
    assert len(before["probes"]) == 1

    await service.reset_for_new_run()
    after = await service.get_probes(include_events=False)

    assert repo.probes_cleared is True
    assert after["probes"] == []


@pytest.mark.asyncio
async def test_probe_service_degrades_when_probe_index_unavailable_spec() -> None:
    service = ProbeService(
        state_repo=_FailingListProbesRepo(),  # type: ignore[arg-type]
        window_s=60,
    )

    snapshot = await service.get_probes(include_events=False)

    assert snapshot["probes"] == []
    assert snapshot["include_events"] is False
