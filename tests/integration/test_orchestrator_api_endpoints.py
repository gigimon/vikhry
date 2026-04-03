from __future__ import annotations

import asyncio
import json
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

import pytest

from vikhry.orchestrator.models.worker import WorkerHealthStatus, WorkerStatus
from vikhry.orchestrator.redis_repo.state_repo import TestStateRepository

pytestmark = pytest.mark.integration


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _run_cli(*args: str) -> None:
    cmd = [sys.executable, "-m", "vikhry.cli", *args]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise AssertionError(
            "CLI command failed:\n"
            f"cmd: {' '.join(cmd)}\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )


def _fetch_json(url: str) -> dict[str, object] | None:
    try:
        with urlopen(url, timeout=0.7) as response:  # noqa: S310
            payload = response.read().decode("utf-8")
    except (URLError, TimeoutError):
        return None
    parsed = json.loads(payload)
    if not isinstance(parsed, dict):
        return None
    return parsed


async def _wait_until(
    predicate,
    *,
    timeout_s: float = 10.0,
    poll_interval_s: float = 0.1,
) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        value = predicate()
        if asyncio.iscoroutine(value):
            value = await value
        if value:
            return
        await asyncio.sleep(poll_interval_s)
    raise AssertionError("condition not met before timeout")


@pytest.mark.asyncio
async def test_workers_and_resources_endpoints_spec(
    docker_redis_url: str,
    state_repo: TestStateRepository,
    tmp_path: Path,
) -> None:
    orchestrator_port = _find_free_port()
    orchestrator_url = f"http://127.0.0.1:{orchestrator_port}"

    orchestrator_pid_file = tmp_path / "orchestrator.pid"
    orchestrator_log_file = tmp_path / "orchestrator.log"
    orchestrator_started = False

    try:
        _run_cli(
            "orchestrator",
            "start",
            "--host",
            "127.0.0.1",
            "--port",
            str(orchestrator_port),
            "--redis-url",
            docker_redis_url,
            "--worker-scan-interval-s",
            "1",
            "--heartbeat-timeout-s",
            "10",
            "--pid-file",
            str(orchestrator_pid_file),
            "--log-file",
            str(orchestrator_log_file),
            "--startup-timeout-s",
            "10",
        )
        orchestrator_started = True

        await _wait_until(
            lambda: _fetch_json(f"{orchestrator_url}/ready") is not None,
            timeout_s=10.0,
        )

        now_ts = int(time.time())
        await state_repo.register_worker("w-alpha")
        await state_repo.set_worker_status(
            "w-alpha",
            WorkerStatus(status=WorkerHealthStatus.HEALTHY, last_heartbeat=now_ts),
        )
        await state_repo.add_worker_user("w-alpha", "1")
        await state_repo.add_worker_user("w-alpha", "2")

        await state_repo.register_worker("w-beta")
        await state_repo.set_worker_status(
            "w-beta",
            WorkerStatus(status=WorkerHealthStatus.UNHEALTHY, last_heartbeat=now_ts - 30),
        )
        await state_repo.add_worker_user("w-beta", "10")

        await state_repo.register_worker("w-gamma")

        workers_payload = _fetch_json(f"{orchestrator_url}/workers")
        assert workers_payload is not None
        assert workers_payload["count"] == 3

        workers = workers_payload["workers"]
        assert isinstance(workers, list)
        assert [worker["worker_id"] for worker in workers] == ["w-alpha", "w-beta", "w-gamma"]

        alpha, beta, gamma = workers
        assert alpha["status"] == "healthy"
        assert alpha["users_count"] == 2
        assert isinstance(alpha["heartbeat_age_s"], int)
        assert alpha["heartbeat_age_s"] >= 0

        assert beta["status"] == "unhealthy"
        assert beta["users_count"] == 1
        assert isinstance(beta["heartbeat_age_s"], int)
        assert beta["heartbeat_age_s"] >= 30

        assert gamma["status"] is None
        assert gamma["last_heartbeat"] is None
        assert gamma["heartbeat_age_s"] is None
        assert gamma["users_count"] == 0

        await state_repo.increment_resource_counter("users", 5)
        await state_repo.increment_resource_counter("accounts", 2)

        resources_payload = _fetch_json(f"{orchestrator_url}/resources")
        assert resources_payload is not None
        assert resources_payload == {
            "generated_at": resources_payload["generated_at"],
            "count": 2,
            "resources": [
                {"resource_name": "accounts", "count": 2},
                {"resource_name": "users", "count": 5},
            ],
        }
        assert isinstance(resources_payload["generated_at"], int)
    finally:
        if orchestrator_started:
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "vikhry.cli",
                    "orchestrator",
                    "stop",
                    "--pid-file",
                    str(orchestrator_pid_file),
                    "--timeout-s",
                    "8",
                    "--force",
                ],
                capture_output=True,
                text=True,
                check=False,
            )


@pytest.mark.asyncio
async def test_probes_endpoints_spec(
    docker_redis_url: str,
    state_repo: TestStateRepository,
    tmp_path: Path,
) -> None:
    orchestrator_port = _find_free_port()
    orchestrator_url = f"http://127.0.0.1:{orchestrator_port}"

    orchestrator_pid_file = tmp_path / "orchestrator.pid"
    orchestrator_log_file = tmp_path / "orchestrator.log"
    orchestrator_started = False

    try:
        _run_cli(
            "orchestrator",
            "start",
            "--host",
            "127.0.0.1",
            "--port",
            str(orchestrator_port),
            "--redis-url",
            docker_redis_url,
            "--worker-scan-interval-s",
            "1",
            "--heartbeat-timeout-s",
            "10",
            "--pid-file",
            str(orchestrator_pid_file),
            "--log-file",
            str(orchestrator_log_file),
            "--startup-timeout-s",
            "10",
        )
        orchestrator_started = True

        await _wait_until(
            lambda: _fetch_json(f"{orchestrator_url}/ready") is not None,
            timeout_s=10.0,
        )

        await state_repo.append_probe_event(
            "db_health",
            {
                "name": "db_health",
                "worker_id": "w-probe",
                "ts_ms": 1_700_000_000_001,
                "status": True,
                "time": 3.2,
                "value": 42,
            },
        )
        await state_repo.append_probe_event(
            "db_health",
            {
                "name": "db_health",
                "worker_id": "w-probe",
                "ts_ms": 1_700_000_000_002,
                "status": False,
                "time": 5.1,
                "value": None,
                "error_type": "RuntimeError",
                "error_message": "boom",
            },
        )
        await state_repo.append_probe_event(
            "cache_health",
            {
                "name": "cache_health",
                "worker_id": "w-probe",
                "ts_ms": 1_700_000_000_003,
                "status": True,
                "time": 1.0,
                "value": 7,
            },
        )

        await _wait_until(
            lambda: (_fetch_json(f"{orchestrator_url}/probes") or {}).get("probes"),
            timeout_s=10.0,
        )

        probes_payload = _fetch_json(f"{orchestrator_url}/probes?include_events=false")
        assert probes_payload is not None
        probes = probes_payload["probes"]
        assert isinstance(probes, list)
        assert [probe["probe_name"] for probe in probes] == ["cache_health", "db_health"]

        db_probe = probes[1]
        assert db_probe["aggregate"] == {
            "window_s": 60,
            "successes": 1,
            "errors": 1,
            "last_ts_ms": 1_700_000_000_002,
            "last_status": False,
            "last_value": None,
        }
        assert db_probe["latest"] == {
            "ts_ms": 1_700_000_000_002,
            "status": False,
            "value": None,
            "time": 5.1,
            "error_type": "RuntimeError",
            "error_message": "boom",
        }
        assert db_probe["events"] is None

        history_payload = _fetch_json(
            f"{orchestrator_url}/probes/history?probe_name=db_health&count=2"
        )
        assert history_payload is not None
        assert history_payload["probe_name"] == "db_health"
        assert history_payload["count"] == 2
        events = history_payload["events"]
        assert isinstance(events, list)
        assert [event["data"]["status"] for event in events] == [True, False]
    finally:
        if orchestrator_started:
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "vikhry.cli",
                    "orchestrator",
                    "stop",
                    "--pid-file",
                    str(orchestrator_pid_file),
                    "--timeout-s",
                    "8",
                    "--force",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
