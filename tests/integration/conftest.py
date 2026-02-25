from __future__ import annotations

import shutil
import socket
import subprocess
import time
from uuid import uuid4

import pytest
import pytest_asyncio
import redis.asyncio as redis

from vikhry.orchestrator.redis_repo.state_repo import TestStateRepository


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _docker_available() -> bool:
    if shutil.which("docker") is None:
        return False
    result = subprocess.run(
        ["docker", "version"],
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode == 0


@pytest.fixture(scope="session")
def docker_redis_url() -> str:
    if not _docker_available():
        pytest.skip("Docker is not available; skipping integration tests")

    container_name = f"vikhry-test-redis-{uuid4().hex[:8]}"
    host_port = _find_free_port()
    redis_url = f"redis://127.0.0.1:{host_port}/0"

    subprocess.run(["docker", "rm", "-f", container_name], check=False, capture_output=True)
    run_result = subprocess.run(
        [
            "docker",
            "run",
            "-d",
            "--name",
            container_name,
            "-p",
            f"{host_port}:6379",
            "redis:7-alpine",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if run_result.returncode != 0:
        pytest.skip(f"Failed to start dockerized redis: {run_result.stderr.strip()}")

    ready = False
    for _ in range(80):
        ping_result = subprocess.run(
            ["docker", "exec", container_name, "redis-cli", "ping"],
            capture_output=True,
            text=True,
            check=False,
        )
        if ping_result.returncode == 0 and "PONG" in ping_result.stdout:
            ready = True
            break
        time.sleep(0.25)

    if not ready:
        subprocess.run(["docker", "rm", "-f", container_name], check=False, capture_output=True)
        pytest.skip("Redis container did not become ready in time")

    try:
        yield redis_url
    finally:
        subprocess.run(["docker", "rm", "-f", container_name], check=False, capture_output=True)


@pytest_asyncio.fixture
async def redis_client(docker_redis_url: str) -> redis.Redis:
    client = redis.Redis.from_url(docker_redis_url, decode_responses=True)
    await client.flushdb()
    try:
        yield client
    finally:
        await client.flushdb()
        await client.aclose()


@pytest_asyncio.fixture
async def state_repo(redis_client: redis.Redis) -> TestStateRepository:
    repo = TestStateRepository(redis_client)
    await repo.initialize_defaults()
    return repo

