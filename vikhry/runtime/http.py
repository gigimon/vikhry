from __future__ import annotations

import asyncio
import inspect
import logging
import time
from collections.abc import Mapping
from datetime import timedelta
from itertools import count
from typing import Any, Protocol
from urllib.parse import urlsplit

from pyreqwest.client import ClientBuilder

from vikhry.runtime.metrics import (
    emit_metric,
    exception_fields,
    extract_status_code,
    is_success_status,
)

logger = logging.getLogger(__name__)

# Chrome stable desktop (Windows/Mac) on March 3, 2026 is 145.0.7632.159/160.
# Keep explicit UA close to a real browser fingerprint and append Vikhry marker.
DEFAULT_HTTP_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/145.0.7632.160 Safari/537.36 Vikhry"
)
JSONRPC_VERSION = "2.0"
JSONRPC_CONTENT_TYPE = "application/json"


class SupportsRequestClient(Protocol):
    async def request(self, method: str, url: str, **kwargs: Any) -> Any: ...


class SupportsJsonRPCClient(Protocol):
    async def call(
        self,
        method: str,
        params: list[Any] | tuple[Any, ...] | dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> Any: ...


SupportsHTTP = SupportsRequestClient | SupportsJsonRPCClient


class SupportsHTTPFactory(Protocol):
    def create(self, *, base_url: str = "") -> SupportsHTTP: ...


class JsonRPCError(RuntimeError):
    def __init__(
        self,
        *,
        code: int | str,
        message: str,
        data: Any = None,
        http_status: int | None = None,
    ) -> None:
        self.code = code
        self.message = str(message)
        self.data = data
        self.http_status = http_status
        super().__init__(self.message)


class JsonRPCProtocolError(RuntimeError):
    pass


class ReqwestHTTPClient:
    def __init__(self, *, base_url: str = "", timeout: float = 30.0) -> None:
        resolved_timeout = max(0.1, timeout)
        self.base_url = base_url
        self.timeout = resolved_timeout
        builder = ClientBuilder().timeout(timedelta(seconds=resolved_timeout))
        builder = builder.user_agent(DEFAULT_HTTP_USER_AGENT)
        if base_url:
            builder = builder.base_url(base_url)
        self._client = builder.build()

    async def request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        json: Any = None,
        data: bytes | str | None = None,
    ) -> Any:
        request_builder = self._client.request(method.upper(), url)
        if params:
            request_builder = request_builder.query(params)
        if headers:
            request_builder = request_builder.headers(headers)
        if json is not None:
            request_builder = request_builder.body_json(json)
        elif data is not None:
            if isinstance(data, str):
                request_builder = request_builder.body_text(data)
            else:
                request_builder = request_builder.body_bytes(data)
        consumed_request = request_builder.build()
        return await maybe_await(consumed_request.send())

    async def get(self, url: str, **kwargs: Any) -> Any:
        return await self.request("GET", url, **kwargs)

    async def post(self, url: str, **kwargs: Any) -> Any:
        return await self.request("POST", url, **kwargs)

    async def put(self, url: str, **kwargs: Any) -> Any:
        return await self.request("PUT", url, **kwargs)

    async def patch(self, url: str, **kwargs: Any) -> Any:
        return await self.request("PATCH", url, **kwargs)

    async def delete(self, url: str, **kwargs: Any) -> Any:
        return await self.request("DELETE", url, **kwargs)

    async def close(self) -> None:
        await maybe_await(self._client.close())


class JsonRPCProtocolClient:
    def __init__(
        self,
        *,
        base_url: str,
        timeout: float = 30.0,
        http_client: SupportsRequestClient | None = None,
    ) -> None:
        normalized_base_url = str(base_url).strip()
        if not normalized_base_url:
            raise ValueError("JsonRPCClient requires non-empty base_url")

        self.base_url = normalized_base_url
        self.timeout = max(0.1, timeout)
        self._http_client = http_client or ReqwestHTTPClient(timeout=self.timeout)
        self._request_ids = count(1)

    async def call(
        self,
        method: str,
        params: list[Any] | tuple[Any, ...] | dict[str, Any] | None = None,
        *,
        headers: dict[str, str] | None = None,
        request_id: int | str | None = None,
    ) -> Any:
        normalized_method = _normalize_jsonrpc_method(method)
        resolved_request_id = request_id if request_id is not None else next(self._request_ids)
        payload: dict[str, Any] = {
            "jsonrpc": JSONRPC_VERSION,
            "id": resolved_request_id,
            "method": normalized_method,
        }
        normalized_params = _normalize_jsonrpc_params(params)
        if normalized_params is not None:
            payload["params"] = normalized_params

        request_headers = {
            "Accept": JSONRPC_CONTENT_TYPE,
            "Content-Type": JSONRPC_CONTENT_TYPE,
        }
        if headers:
            request_headers.update(headers)

        response = await maybe_await(
            self._http_client.request(
                "POST",
                self.base_url,
                headers=request_headers,
                json=payload,
            )
        )
        status_code = extract_status_code(response)
        response_payload = await maybe_await(response.json())
        return _parse_jsonrpc_response(
            response_payload,
            request_id=resolved_request_id,
            http_status=status_code,
        )

    async def close(self) -> None:
        await close_http_client(self._http_client)


class InstrumentedHTTPClient:
    def __init__(self, client: SupportsHTTP) -> None:
        self._client = client

    async def request(self, method: str, url: str, **kwargs: Any) -> Any:
        method_name = str(method).upper()
        metric_name = _metric_name_from_url(url)
        started_at = time.perf_counter()
        status_code: int | None = None
        status = False
        result_code = "HTTP_EXCEPTION"
        result_category = "transport_error"
        error_type: str | None = None
        error_message: str | None = None
        traceback: str | None = None
        cancelled = False

        try:
            response = await maybe_await(self._client.request(method_name, url, **kwargs))
            status_code = extract_status_code(response)
            status = is_success_status(status_code)
            if status_code is None:
                result_code = "HTTP_OK"
                result_category = "ok"
            else:
                result_code = f"HTTP_{status_code}"
                result_category = "ok" if status else "protocol_error"
            return response
        except asyncio.CancelledError:
            cancelled = True
            raise
        except Exception as exc:  # noqa: BLE001
            error_payload = exception_fields(exc)
            error_type = error_payload["error_type"]
            error_message = error_payload["error_message"]
            traceback = error_payload["traceback"]
            if isinstance(exc, (TimeoutError, asyncio.TimeoutError)):
                result_code = "HTTP_TIMEOUT"
                result_category = "timeout"
            raise
        finally:
            if not cancelled:
                elapsed_ms = round((time.perf_counter() - started_at) * 1000, 3)
                metric_fields: dict[str, Any] = {
                    "method": method_name,
                    "url": url,
                }
                if status_code is not None:
                    metric_fields["status_code"] = status_code
                try:
                    await emit_metric(
                        name=metric_name,
                        status=status,
                        time=elapsed_ms,
                        source="http",
                        stage="execute",
                        result_code=result_code,
                        result_category=result_category,
                        fatal=False,
                        error_type=error_type,
                        error_message=error_message,
                        traceback=traceback,
                        **metric_fields,
                    )
                except Exception:  # noqa: BLE001
                    logger.debug("failed to emit http metric", exc_info=True)

    async def get(self, url: str, **kwargs: Any) -> Any:
        return await self.request("GET", url, **kwargs)

    async def post(self, url: str, **kwargs: Any) -> Any:
        return await self.request("POST", url, **kwargs)

    async def put(self, url: str, **kwargs: Any) -> Any:
        return await self.request("PUT", url, **kwargs)

    async def patch(self, url: str, **kwargs: Any) -> Any:
        return await self.request("PATCH", url, **kwargs)

    async def delete(self, url: str, **kwargs: Any) -> Any:
        return await self.request("DELETE", url, **kwargs)

    async def close(self) -> None:
        await close_http_client(self._client)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._client, name)


class InstrumentedJsonRPCClient:
    def __init__(self, client: SupportsJsonRPCClient) -> None:
        self._client = client

    async def call(
        self,
        method: str,
        params: list[Any] | tuple[Any, ...] | dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> Any:
        rpc_method = _normalize_jsonrpc_method(method)
        started_at = time.perf_counter()
        status = False
        result_code = "JSONRPC_EXCEPTION"
        result_category = "transport_error"
        error_type: str | None = None
        error_message: str | None = None
        traceback: str | None = None
        http_status: int | None = None
        rpc_error_code: int | str | None = None
        cancelled = False

        try:
            result = await maybe_await(self._client.call(rpc_method, params=params, **kwargs))
            status = True
            result_code = "JSONRPC_OK"
            result_category = "ok"
            return result
        except asyncio.CancelledError:
            cancelled = True
            raise
        except JsonRPCError as exc:
            rpc_error_code = exc.code
            http_status = exc.http_status
            error_type = type(exc).__name__
            error_message = exc.message
            traceback = exception_fields(exc)["traceback"]
            result_code = _jsonrpc_result_code_from_error_code(exc.code)
            result_category = "rpc_error"
            raise
        except JsonRPCProtocolError as exc:
            error_payload = exception_fields(exc)
            error_type = error_payload["error_type"]
            error_message = error_payload["error_message"]
            traceback = error_payload["traceback"]
            result_code = "JSONRPC_PROTOCOL_ERROR"
            result_category = "protocol_error"
            raise
        except Exception as exc:  # noqa: BLE001
            error_payload = exception_fields(exc)
            error_type = error_payload["error_type"]
            error_message = error_payload["error_message"]
            traceback = error_payload["traceback"]
            if isinstance(exc, (TimeoutError, asyncio.TimeoutError)):
                result_code = "JSONRPC_TIMEOUT"
                result_category = "timeout"
            raise
        finally:
            if not cancelled:
                elapsed_ms = round((time.perf_counter() - started_at) * 1000, 3)
                metric_fields: dict[str, Any] = {
                    "rpc_method": rpc_method,
                }
                base_url = getattr(self._client, "base_url", None)
                if isinstance(base_url, str) and base_url.strip():
                    metric_fields["url"] = base_url
                if http_status is not None:
                    metric_fields["http_status"] = http_status
                if rpc_error_code is not None:
                    metric_fields["rpc_error_code"] = rpc_error_code
                try:
                    await emit_metric(
                        name=rpc_method,
                        status=status,
                        time=elapsed_ms,
                        source="jsonrpc",
                        stage="execute",
                        result_code=result_code,
                        result_category=result_category,
                        fatal=False,
                        error_type=error_type,
                        error_message=error_message,
                        traceback=traceback,
                        **metric_fields,
                    )
                except Exception:  # noqa: BLE001
                    logger.debug("failed to emit jsonrpc metric", exc_info=True)

    async def close(self) -> None:
        await close_http_client(self._client)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._client, name)


class ReqwestClient:
    """Lazy factory template for per-VU reqwest client instances."""

    def __init__(self, *, base_url: str = "", timeout: float = 30.0) -> None:
        self.base_url = base_url
        self.timeout = timeout

    def create(self, *, base_url: str = "") -> ReqwestHTTPClient:
        resolved_base_url = base_url or self.base_url
        return ReqwestHTTPClient(base_url=resolved_base_url, timeout=self.timeout)

    def __call__(
        self,
        *,
        base_url: str = "",
        timeout: float | None = None,
    ) -> SupportsHTTP:
        if timeout is None:
            return instrument_http_client(self.create(base_url=base_url))

        resolved_base_url = base_url or self.base_url
        return instrument_http_client(
            ReqwestHTTPClient(base_url=resolved_base_url, timeout=timeout)
        )


class JsonRPCClient:
    """Lazy factory template for per-VU JSON-RPC client instances."""

    def __init__(self, *, base_url: str = "", timeout: float = 30.0) -> None:
        self.base_url = base_url
        self.timeout = timeout

    def create(self, *, base_url: str = "") -> JsonRPCProtocolClient:
        resolved_base_url = base_url or self.base_url
        return JsonRPCProtocolClient(base_url=resolved_base_url, timeout=self.timeout)

    def __call__(
        self,
        *,
        base_url: str = "",
        timeout: float | None = None,
    ) -> SupportsHTTP:
        if timeout is None:
            return instrument_http_client(self.create(base_url=base_url))

        resolved_base_url = base_url or self.base_url
        return instrument_http_client(
            JsonRPCProtocolClient(base_url=resolved_base_url, timeout=timeout)
        )


def resolve_http_client(http_spec: object, *, base_url: str = "") -> SupportsHTTP:
    if _is_runtime_client(http_spec):
        return instrument_http_client(http_spec)

    if isinstance(http_spec, ReqwestClient):
        return instrument_http_client(http_spec.create(base_url=base_url))
    if isinstance(http_spec, JsonRPCClient):
        return instrument_http_client(http_spec.create(base_url=base_url))

    create = getattr(http_spec, "create", None)
    if callable(create):
        try:
            client = create(base_url=base_url)
        except TypeError:
            client = create()
        if not _is_runtime_client(client):
            raise TypeError("http factory create() must return object with async request() or call()")
        return instrument_http_client(client)

    if inspect.isclass(http_spec):
        instance = http_spec()
        if _is_runtime_client(instance):
            return instrument_http_client(instance)

    if callable(http_spec):
        try:
            client = http_spec(base_url=base_url)
        except TypeError:
            client = http_spec()
        if not _is_runtime_client(client):
            raise TypeError("http callable factory must return object with async request() or call()")
        return instrument_http_client(client)

    raise TypeError(
        "VU http attribute must be a client or factory with request(), call(), or create()"
    )


async def close_http_client(http_client: SupportsHTTP | None) -> None:
    if http_client is None:
        return

    close_fn = getattr(http_client, "close", None)
    if callable(close_fn):
        await maybe_await(close_fn())
        return

    aclose_fn = getattr(http_client, "aclose", None)
    if callable(aclose_fn):
        await maybe_await(aclose_fn())


async def maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def _is_http_client(value: object) -> bool:
    return callable(getattr(value, "request", None))


def _is_jsonrpc_client(value: object) -> bool:
    return callable(getattr(value, "call", None))


def _is_runtime_client(value: object) -> bool:
    return _is_http_client(value) or _is_jsonrpc_client(value)


def instrument_http_client(client: SupportsHTTP) -> SupportsHTTP:
    if isinstance(client, (InstrumentedHTTPClient, InstrumentedJsonRPCClient)):
        return client
    if _is_http_client(client):
        return InstrumentedHTTPClient(client)
    if _is_jsonrpc_client(client):
        return InstrumentedJsonRPCClient(client)
    raise TypeError("unsupported client type for instrumentation")


def _parse_jsonrpc_response(
    payload: Any,
    *,
    request_id: int | str,
    http_status: int | None,
) -> Any:
    if not isinstance(payload, dict):
        raise JsonRPCProtocolError("JSON-RPC response must be an object")
    if payload.get("jsonrpc") != JSONRPC_VERSION:
        raise JsonRPCProtocolError("JSON-RPC response must declare jsonrpc=2.0")
    if payload.get("id") != request_id:
        raise JsonRPCProtocolError("JSON-RPC response id mismatch")

    error_payload = payload.get("error")
    if error_payload is not None:
        if not isinstance(error_payload, dict):
            raise JsonRPCProtocolError("JSON-RPC error payload must be an object")
        if "code" not in error_payload or "message" not in error_payload:
            raise JsonRPCProtocolError("JSON-RPC error payload must contain code and message")
        raise JsonRPCError(
            code=error_payload["code"],
            message=str(error_payload["message"]),
            data=error_payload.get("data"),
            http_status=http_status,
        )

    if "result" not in payload:
        raise JsonRPCProtocolError("JSON-RPC response must contain result or error")
    return payload["result"]


def _normalize_jsonrpc_method(method: str) -> str:
    normalized = str(method).strip()
    if not normalized:
        raise ValueError("json-rpc method must not be empty")
    return normalized


def _normalize_jsonrpc_params(
    params: list[Any] | tuple[Any, ...] | dict[str, Any] | None,
) -> list[Any] | dict[str, Any] | None:
    if params is None:
        return None
    if isinstance(params, tuple):
        return list(params)
    if isinstance(params, list):
        return params
    if isinstance(params, Mapping):
        return dict(params)
    raise TypeError("json-rpc params must be list, tuple, dict, or None")


def _jsonrpc_result_code_from_error_code(code: int | str) -> str:
    normalized = str(code).strip()
    if not normalized:
        return "JSONRPC_ERROR"
    return f"JSONRPC_{normalized}"


def _metric_name_from_url(url: str) -> str:
    parsed = urlsplit(url)
    path = parsed.path
    if not path:
        raw_path = str(url).split("?", maxsplit=1)[0]
        path = raw_path if raw_path else "/"
    if not path.startswith("/"):
        return f"/{path}"
    return path
