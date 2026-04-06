from __future__ import annotations

import asyncio
import logging
from collections import deque

import pytest

from vikhry.worker.app import _configure_logging, _wait_for_redis_or_retry


class _FakeRedisClient:
    def __init__(self, outcomes: list[object]) -> None:
        self._outcomes = deque(outcomes)
        self.ping_calls = 0

    async def ping(self) -> bool:
        self.ping_calls += 1
        outcome = self._outcomes.popleft() if self._outcomes else True
        if isinstance(outcome, Exception):
            raise outcome
        return bool(outcome)


@pytest.mark.asyncio
async def test_worker_wait_for_redis_or_retry_passes_on_first_ping_spec() -> None:
    client = _FakeRedisClient([True])
    connected = await _wait_for_redis_or_retry(
        redis_client=client,  # type: ignore[arg-type]
        redis_url="redis://127.0.0.1:6379/0",
        retry_delay_s=5.0,
        worker_id="w-test",
    )
    assert connected is True
    assert client.ping_calls == 1


@pytest.mark.asyncio
async def test_worker_wait_for_redis_or_retry_retries_every_5_seconds_until_success_spec(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _FakeRedisClient(
        [
            RuntimeError("connection refused"),
            RuntimeError("connection refused"),
            True,
        ]
    )
    sleep_calls: list[float] = []

    async def _fake_sleep(delay: float) -> None:
        sleep_calls.append(delay)

    monkeypatch.setattr("vikhry.worker.app.asyncio.sleep", _fake_sleep)

    connected = await _wait_for_redis_or_retry(
        redis_client=client,  # type: ignore[arg-type]
        redis_url="redis://127.0.0.1:6379/0",
        retry_delay_s=5.0,
        worker_id="w-test",
    )

    assert connected is True
    assert client.ping_calls == 3
    assert sleep_calls == [5.0, 5.0]


@pytest.mark.asyncio
async def test_worker_wait_for_redis_or_retry_stops_when_shutdown_requested_spec() -> None:
    client = _FakeRedisClient([RuntimeError("connection refused")])
    shutdown_event = asyncio.Event()
    shutdown_event.set()

    connected = await _wait_for_redis_or_retry(
        redis_client=client,  # type: ignore[arg-type]
        redis_url="redis://127.0.0.1:6379/0",
        retry_delay_s=5.0,
        worker_id="w-test",
        shutdown_event=shutdown_event,
    )

    assert connected is False
    assert client.ping_calls == 1


def test_configure_logging_replaces_preexisting_root_handlers_spec() -> None:
    root = logging.getLogger()
    original_handlers = list(root.handlers)
    original_level = root.level
    sentinel_handler = logging.NullHandler()

    for handler in list(root.handlers):
        root.removeHandler(handler)
    root.addHandler(sentinel_handler)
    root.setLevel(logging.NOTSET)

    try:
        _configure_logging("WARNING")
        assert sentinel_handler not in root.handlers
        assert root.level == logging.WARNING
    finally:
        for handler in list(root.handlers):
            root.removeHandler(handler)
            handler.close()
        for handler in original_handlers:
            root.addHandler(handler)
        root.setLevel(original_level)
