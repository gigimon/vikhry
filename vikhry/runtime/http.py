from __future__ import annotations

import inspect
from datetime import timedelta
from typing import Any, Protocol

from pyreqwest.client import ClientBuilder


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
        return http_spec

    if isinstance(http_spec, ReqwestClient):
        return http_spec.create(base_url=base_url)

    create = getattr(http_spec, "create", None)
    if callable(create):
        try:
            client = create(base_url=base_url)
        except TypeError:
            client = create()
        if not _is_http_client(client):
            raise TypeError("http factory create() must return object with async request()")
        return client

    if inspect.isclass(http_spec):
        instance = http_spec()
        if _is_http_client(instance):
            return instance

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
