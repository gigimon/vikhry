from __future__ import annotations

import pytest

from vikhry.runtime.http import (
    JsonRPCClient,
    JsonRPCError,
    JsonRPCProtocolClient,
    resolve_http_client,
)
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


class _JsonRPCResponse:
    def __init__(self, status: int, payload: object) -> None:
        self.status = status
        self._payload = payload

    def json(self) -> object:
        return self._payload


class _RecordingRequestClient:
    def __init__(self, response: _JsonRPCResponse) -> None:
        self.response = response
        self.calls: list[tuple[str, str, dict[str, object]]] = []

    async def request(self, method: str, url: str, **kwargs: object) -> _JsonRPCResponse:
        self.calls.append((method, url, dict(kwargs)))
        return self.response

    async def close(self) -> None:
        return None


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
    assert "Traceback (most recent call last):" in str(captured[0]["traceback"])
    assert "RuntimeError: boom" in str(captured[0]["traceback"])


@pytest.mark.asyncio
async def test_jsonrpc_protocol_client_builds_post_request_and_returns_result_spec() -> None:
    transport = _RecordingRequestClient(
        _JsonRPCResponse(
            200,
            {"jsonrpc": "2.0", "id": 1, "result": {"ok": True}},
        )
    )
    client = JsonRPCProtocolClient(
        base_url="http://localhost:8000/rpc",
        http_client=transport,
    )

    result = await client.call("user.get", {"user_id": 42})

    assert result == {"ok": True}
    assert transport.calls == [
        (
            "POST",
            "http://localhost:8000/rpc",
            {
                "headers": {
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
                "json": {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "user.get",
                    "params": {"user_id": 42},
                },
            },
        )
    ]


@pytest.mark.asyncio
async def test_jsonrpc_protocol_client_raises_on_error_payload_spec() -> None:
    transport = _RecordingRequestClient(
        _JsonRPCResponse(
            200,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "error": {"code": -32601, "message": "Method not found"},
            },
        )
    )
    client = JsonRPCProtocolClient(
        base_url="http://localhost:8000/rpc",
        http_client=transport,
    )

    with pytest.raises(JsonRPCError) as exc_info:
        await client.call("user.get")

    assert exc_info.value.code == -32601
    assert exc_info.value.message == "Method not found"


@pytest.mark.asyncio
async def test_jsonrpc_client_emits_metric_with_rpc_error_code_spec() -> None:
    captured: list[dict[str, object]] = []

    async def _emitter(payload: dict[str, object]) -> None:
        captured.append(payload)

    transport = _RecordingRequestClient(
        _JsonRPCResponse(
            200,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "error": {"code": -32000, "message": "Upstream failed"},
            },
        )
    )
    client = resolve_http_client(
        JsonRPCProtocolClient(
            base_url="http://localhost:8000/rpc",
            http_client=transport,
        )
    )

    with pytest.raises(JsonRPCError, match="Upstream failed"):
        with metric_scope(emitter=_emitter, step="rpc_step"):
            await client.call("orders.create", {"id": 7})

    assert len(captured) == 1
    assert captured[0]["name"] == "orders.create"
    assert captured[0]["step"] == "rpc_step"
    assert captured[0]["source"] == "jsonrpc"
    assert captured[0]["result_code"] == "JSONRPC_-32000"
    assert captured[0]["result_category"] == "rpc_error"
    assert captured[0]["rpc_error_code"] == -32000
    assert captured[0]["http_status"] == 200


def test_resolve_http_client_supports_jsonrpc_factory_spec() -> None:
    client = resolve_http_client(JsonRPCClient(base_url="http://localhost:8000/rpc"))
    assert callable(getattr(client, "call", None))
