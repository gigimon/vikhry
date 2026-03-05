from __future__ import annotations

from collections import deque

import pytest

from vikhry.orchestrator.app import _wait_for_redis_or_retry


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
async def test_wait_for_redis_or_retry_passes_on_first_ping_spec() -> None:
    client = _FakeRedisClient([True])
    await _wait_for_redis_or_retry(
        redis_client=client,  # type: ignore[arg-type]
        redis_url="redis://127.0.0.1:6379/0",
        retry_delay_s=5.0,
    )
    assert client.ping_calls == 1


@pytest.mark.asyncio
async def test_wait_for_redis_or_retry_retries_every_5_seconds_until_success_spec(
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

    monkeypatch.setattr("vikhry.orchestrator.app.asyncio.sleep", _fake_sleep)

    await _wait_for_redis_or_retry(
        redis_client=client,  # type: ignore[arg-type]
        redis_url="redis://127.0.0.1:6379/0",
        retry_delay_s=5.0,
    )

    assert client.ping_calls == 3
    assert sleep_calls == [5.0, 5.0]
