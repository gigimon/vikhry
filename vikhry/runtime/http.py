from __future__ import annotations

import asyncio
import inspect
import logging
import time
from urllib.parse import urlsplit
from datetime import timedelta
from typing import Any, Protocol

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


class SupportsHTTP(Protocol):
    async def request(self, method: str, url: str, **kwargs: Any) -> Any: ...


class SupportsHTTPFactory(Protocol):
    def create(self, *, base_url: str = "") -> SupportsHTTP: ...


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


def resolve_http_client(http_spec: object, *, base_url: str = "") -> SupportsHTTP:
    if _is_http_client(http_spec):
        return instrument_http_client(http_spec)

    if isinstance(http_spec, ReqwestClient):
        return instrument_http_client(http_spec.create(base_url=base_url))

    create = getattr(http_spec, "create", None)
    if callable(create):
        try:
            client = create(base_url=base_url)
        except TypeError:
            client = create()
        if not _is_http_client(client):
            raise TypeError("http factory create() must return object with async request()")
        return instrument_http_client(client)

    if inspect.isclass(http_spec):
        instance = http_spec()
        if _is_http_client(instance):
            return instrument_http_client(instance)

    if callable(http_spec):
        try:
            client = http_spec(base_url=base_url)
        except TypeError:
            client = http_spec()
        if not _is_http_client(client):
            raise TypeError("http callable factory must return object with async request()")
        return instrument_http_client(client)

    raise TypeError(
        "VU http attribute must be an HTTP client or factory with create()"
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


def instrument_http_client(client: SupportsHTTP) -> SupportsHTTP:
    if isinstance(client, InstrumentedHTTPClient):
        return client
    return InstrumentedHTTPClient(client)


def _metric_name_from_url(url: str) -> str:
    parsed = urlsplit(url)
    path = parsed.path
    if not path:
        raw_path = str(url).split("?", maxsplit=1)[0]
        path = raw_path if raw_path else "/"
    if not path.startswith("/"):
        return f"/{path}"
    return path
