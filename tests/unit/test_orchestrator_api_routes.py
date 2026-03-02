from __future__ import annotations

from types import SimpleNamespace

import pytest

from vikhry.orchestrator.api.routes import (
    _query_bool,
    _query_int,
    _query_value,
    _build_resources_response,
    _build_workers_response,
)
from vikhry.orchestrator.models.worker import WorkerStatus


class _FakeStateRepo:
    def __init__(self) -> None:
        self._workers = ["w1", "w2", "w3"]
        self._statuses = {
            "w1": WorkerStatus(status="healthy", last_heartbeat=95),
            "w3": WorkerStatus(status="unhealthy", last_heartbeat=50),
        }
        self._worker_users = {
            "w1": ["1", "2"],
            "w2": [],
            "w3": ["10"],
        }
        self._resources = {
            "users": 10,
            "accounts": 3,
        }

    async def list_workers(self) -> list[str]:
        return list(self._workers)

    async def get_worker_status(self, worker_id: str) -> WorkerStatus | None:
        return self._statuses.get(worker_id)

    async def list_worker_users(self, worker_id: str) -> list[str]:
        return list(self._worker_users.get(worker_id, []))

    async def list_resource_counters(self) -> dict[str, int]:
        return dict(self._resources)


class _FakeWorkerPresence:
    def __init__(self, now_ts: int) -> None:
        self._now_ts = now_ts

    def now_ts(self) -> int:
        return self._now_ts


class _QueryParamsLike:
    def __init__(self, data: dict[str, object]) -> None:
        self._data = data

    def get(self, key: str, default: object) -> object:
        return self._data.get(key, default)


@pytest.mark.asyncio
async def test_build_workers_response_includes_status_heartbeat_and_user_counts_spec() -> None:
    result = await _build_workers_response(
        state_repo=_FakeStateRepo(),  # type: ignore[arg-type]
        worker_presence=_FakeWorkerPresence(now_ts=100),  # type: ignore[arg-type]
    )

    assert result["generated_at"] == 100
    assert result["count"] == 3
    assert result["workers"] == [
        {
            "worker_id": "w1",
            "status": "healthy",
            "last_heartbeat": 95,
            "heartbeat_age_s": 5,
            "users_count": 2,
            "cpu_percent": None,
            "process_ram_bytes": None,
            "total_ram_bytes": None,
        },
        {
            "worker_id": "w2",
            "status": None,
            "last_heartbeat": None,
            "heartbeat_age_s": None,
            "users_count": 0,
            "cpu_percent": None,
            "process_ram_bytes": None,
            "total_ram_bytes": None,
        },
        {
            "worker_id": "w3",
            "status": "unhealthy",
            "last_heartbeat": 50,
            "heartbeat_age_s": 50,
            "users_count": 1,
            "cpu_percent": None,
            "process_ram_bytes": None,
            "total_ram_bytes": None,
        },
    ]


@pytest.mark.asyncio
async def test_build_resources_response_returns_sorted_resource_counters_spec() -> None:
    result = await _build_resources_response(
        state_repo=_FakeStateRepo(),  # type: ignore[arg-type]
        now_ts=123,
    )

    assert result == {
        "generated_at": 123,
        "count": 2,
        "resources": [
            {"resource_name": "accounts", "count": 3},
            {"resource_name": "users", "count": 10},
        ],
    }


@pytest.mark.asyncio
async def test_build_resources_response_includes_declared_names_with_zero_count_spec() -> None:
    result = await _build_resources_response(
        state_repo=_FakeStateRepo(),  # type: ignore[arg-type]
        now_ts=321,
        declared_resource_names=["users", "orders"],
    )

    assert result == {
        "generated_at": 321,
        "count": 3,
        "resources": [
            {"resource_name": "accounts", "count": 3},
            {"resource_name": "orders", "count": 0},
            {"resource_name": "users", "count": 10},
        ],
    }


def test_query_helpers_support_query_params_get_with_required_default_spec() -> None:
    request = SimpleNamespace(
        query_params=_QueryParamsLike(
            {
                "count": "200",
                "include_events": "false",
                "metric_id": "m1",
            }
        )
    )
    assert _query_value(request, "metric_id") == "m1"  # type: ignore[arg-type]
    assert _query_int(request, key="count", default=100, min_value=1, max_value=1000) == 200  # type: ignore[arg-type]
    assert _query_bool(request, key="include_events", default=True) is False  # type: ignore[arg-type]
