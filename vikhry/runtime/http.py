from __future__ import annotations

import asyncio
import inspect
import logging
import time
from urllib.parse import urlsplit
from datetime import timedelta
from typing import Any, Protocol

from pyreqwest.client import ClientBuilder

from vikhry.runtime.metrics import emit_metric, extract_status_code, is_success_status

logger = logging.getLogger(__name__)


class SupportsHTTP(Protocol):
    async def request(self, method: str, url: str, **kwargs: Any) -> Any: ...


class SupportsHTTPFactory(Protocol):
    def create(self, *, base_url: str = "") -> SupportsHTTP: ...


class ReqwestHTTPClient:
    def __init__(self, *, base_url: str = "", timeout: float = 30.0) -> None:
        builder = ClientBuilder().timeout(timedelta(seconds=max(0.1, timeout)))
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
        error_text: str | None = None
        cancelled = False

        try:
            response = await maybe_await(self._client.request(method_name, url, **kwargs))
            status_code = extract_status_code(response)
            status = is_success_status(status_code)
            return response
        except asyncio.CancelledError:
            cancelled = True
            raise
        except Exception as exc:  # noqa: BLE001
            error_text = f"{type(exc).__name__}: {exc}"
            raise
        finally:
            if not cancelled:
                elapsed_ms = round((time.perf_counter() - started_at) * 1000, 3)
                metric_fields: dict[str, Any] = {
                    "kind": "http",
                    "method": method_name,
                    "url": url,
                }
                if status_code is not None:
                    metric_fields["status_code"] = status_code
                if error_text is not None:
                    metric_fields["error"] = error_text
                try:
                    await emit_metric(
                        name=metric_name,
                        status=status,
                        time=elapsed_ms,
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
