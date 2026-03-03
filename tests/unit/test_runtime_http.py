from __future__ import annotations

import pytest

from vikhry.runtime.http import resolve_http_client
from vikhry.runtime.metrics import metric_scope


class _Response:
    def __init__(self, status: int) -> None:
        self.status = status


class _FakeHTTPClient:
    async def request(self, method: str, url: str, **kwargs: object) -> _Response:
        _ = (method, url, kwargs)
        return _Response(204)

    async def close(self) -> None:
        return None


class _ErrorHTTPClient:
    async def request(self, method: str, url: str, **kwargs: object) -> _Response:
        _ = (method, url, kwargs)
        raise RuntimeError("boom")


@pytest.mark.asyncio
async def test_http_client_emits_metric_with_path_name_spec() -> None:
    captured: list[dict[str, object]] = []

    async def _emitter(payload: dict[str, object]) -> None:
        captured.append(payload)

    client = resolve_http_client(_FakeHTTPClient())

    with metric_scope(emitter=_emitter, step="ping"):
        response = await client.request("get", "http://localhost:8000/page1?q=1")

    assert response.status == 204
    assert len(captured) == 1
    assert captured[0]["name"] == "/page1"
    assert captured[0]["step"] == "ping"
    assert captured[0]["status"] is True
    assert captured[0]["source"] == "http"
    assert captured[0]["stage"] == "execute"
    assert captured[0]["result_code"] == "HTTP_204"
    assert captured[0]["result_category"] == "ok"
    assert captured[0]["fatal"] is False
    assert captured[0]["method"] == "GET"
    assert captured[0]["status_code"] == 204


@pytest.mark.asyncio
async def test_http_client_emits_failed_metric_on_exception_spec() -> None:
    captured: list[dict[str, object]] = []

    async def _emitter(payload: dict[str, object]) -> None:
        captured.append(payload)

    client = resolve_http_client(_ErrorHTTPClient())

    with pytest.raises(RuntimeError, match="boom"):
        with metric_scope(emitter=_emitter, step="ping"):
            await client.request("post", "/auth")

    assert len(captured) == 1
    assert captured[0]["name"] == "/auth"
    assert captured[0]["step"] == "ping"
    assert captured[0]["status"] is False
    assert captured[0]["source"] == "http"
    assert captured[0]["stage"] == "execute"
    assert captured[0]["result_code"] == "HTTP_EXCEPTION"
    assert captured[0]["result_category"] == "transport_error"
    assert captured[0]["fatal"] is False
    assert captured[0]["method"] == "POST"
    assert captured[0]["error_type"] == "RuntimeError"
    assert captured[0]["error_message"] == "boom"
