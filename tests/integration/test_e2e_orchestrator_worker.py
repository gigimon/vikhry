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
import redis.asyncio as redis

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


async def _redis_get_equals(redis_client: redis.Redis, key: str, expected: str) -> bool:
    return (await redis_client.get(key)) == expected


async def _redis_scard_equals(redis_client: redis.Redis, key: str, expected: int) -> bool:
    return (await redis_client.scard(key)) == expected


@pytest.mark.asyncio
async def test_e2e_orchestrator_worker_cli_redis_visibility_spec(
    redis_client: redis.Redis,
    docker_redis_url: str,
    tmp_path: Path,
) -> None:
    orchestrator_port = _find_free_port()
    orchestrator_url = f"http://127.0.0.1:{orchestrator_port}"
    worker_id = "w-e2e-01"

    orchestrator_pid_file = tmp_path / "orchestrator.pid"
    orchestrator_log_file = tmp_path / "orchestrator.log"
    worker_pid_file = tmp_path / "worker.pid"
    worker_log_file = tmp_path / "worker.log"

    orchestrator_started = False
    worker_started = False

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

        _run_cli(
            "worker",
            "start",
            "--redis-url",
            docker_redis_url,
            "--worker-id",
            worker_id,
            "--heartbeat-interval-s",
            "0.2",
            "--pid-file",
            str(worker_pid_file),
            "--log-file",
            str(worker_log_file),
            "--startup-timeout-s",
            "10",
        )
        worker_started = True

        await _wait_until(
            lambda: _fetch_json(f"{orchestrator_url}/ready"),
            timeout_s=10.0,
        )
        await _wait_until(
            lambda: (
                (ready := _fetch_json(f"{orchestrator_url}/ready")) is not None
                and bool(ready.get("ready"))
                and int(ready.get("alive_workers", 0)) >= 1
                and worker_id in list(ready.get("workers", []))
            ),
            timeout_s=10.0,
        )

        workers = await redis_client.smembers("workers")
        assert worker_id in workers

        worker_status_key = f"worker:{worker_id}:status"
        status_before = await redis_client.hgetall(worker_status_key)
        assert status_before.get("status") == "healthy"
        first_heartbeat = int(status_before["last_heartbeat"])
        await asyncio.sleep(0.35)
        status_after = await redis_client.hgetall(worker_status_key)
        assert int(status_after["last_heartbeat"]) >= first_heartbeat

        _run_cli(
            "test",
            "start",
            "--users",
            "3",
            "--orchestrator-url",
            orchestrator_url,
            "--timeout-s",
            "10",
        )

        await _wait_until(
            lambda: redis_client.get("test:state"),
            timeout_s=5.0,
        )
        await _wait_until(
            lambda: _redis_get_equals(redis_client, "test:state", "RUNNING"),
            timeout_s=5.0,
        )
        await _wait_until(
            lambda: _redis_scard_equals(redis_client, "users", 3),
            timeout_s=5.0,
        )
        assert await redis_client.scard(f"worker:{worker_id}:users") == 3
        await _wait_until(
            lambda: _redis_scard_equals(redis_client, f"worker:{worker_id}:active_users", 3),
            timeout_s=5.0,
        )
        for user_id in ("1", "2", "3"):
            raw_user = await redis_client.hgetall(f"user:{user_id}")
            assert raw_user.get("worker_id") == worker_id
            assert raw_user.get("status") == "running"

        _run_cli(
            "test",
            "change-users",
            "--users",
            "5",
            "--orchestrator-url",
            orchestrator_url,
            "--timeout-s",
            "10",
        )
        await _wait_until(
            lambda: _redis_scard_equals(redis_client, "users", 5),
            timeout_s=5.0,
        )
        assert await redis_client.scard(f"worker:{worker_id}:users") == 5
        await _wait_until(
            lambda: _redis_scard_equals(redis_client, f"worker:{worker_id}:active_users", 5),
            timeout_s=5.0,
        )

        _run_cli(
            "test",
            "change-users",
            "--users",
            "2",
            "--orchestrator-url",
            orchestrator_url,
            "--timeout-s",
            "10",
        )
        await _wait_until(
            lambda: _redis_scard_equals(redis_client, "users", 2),
            timeout_s=5.0,
        )
        assert await redis_client.scard(f"worker:{worker_id}:users") == 2
        await _wait_until(
            lambda: _redis_scard_equals(redis_client, f"worker:{worker_id}:active_users", 2),
            timeout_s=5.0,
        )

        _run_cli(
            "test",
            "stop",
            "--orchestrator-url",
            orchestrator_url,
            "--timeout-s",
            "10",
        )
        await _wait_until(
            lambda: _redis_get_equals(redis_client, "test:state", "IDLE"),
            timeout_s=5.0,
        )
        await _wait_until(
            lambda: _redis_scard_equals(redis_client, "users", 0),
            timeout_s=5.0,
        )
        assert await redis_client.exists(f"worker:{worker_id}:users") == 0
        assert await redis_client.exists(f"worker:{worker_id}:active_users") == 0
    finally:
        if worker_started:
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "vikhry.cli",
                    "worker",
                    "stop",
                    "--pid-file",
                    str(worker_pid_file),
                    "--timeout-s",
                    "8",
                    "--force",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
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
