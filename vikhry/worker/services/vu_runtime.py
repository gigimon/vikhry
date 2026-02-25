from __future__ import annotations

import asyncio
import importlib
import inspect
import logging
import random
import time
from collections.abc import Awaitable
from datetime import timedelta
from typing import Any

from pyreqwest.client import ClientBuilder

from vikhry.runtime import VU, bind_steps
from vikhry.worker.redis_repo.state_repo import WorkerStateRepository

logger = logging.getLogger(__name__)

DEFAULT_SCENARIO_IMPORT = "vikhry.runtime.defaults:IdleVU"


class WorkerVUHttpClient:
    def __init__(self, *, base_url: str = "", timeout_s: float = 30.0) -> None:
        builder = ClientBuilder().timeout(timedelta(seconds=max(0.1, timeout_s)))
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
        return await _maybe_await(consumed_request.send())

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
        await _maybe_await(self._client.close())


class WorkerVUResources:
    def __init__(self, state_repo: WorkerStateRepository) -> None:
        self._state_repo = state_repo

    async def acquire(self, resource_name: str) -> dict[str, Any]:
        payload = await self._state_repo.acquire_resource_data(resource_name)
        if payload is None:
            raise RuntimeError(f"resource pool `{resource_name}` is empty")
        return payload

    async def release(self, resource_name: str, resource_id: int | str) -> None:
        await self._state_repo.release_resource(resource_name, resource_id)


class WorkerVURuntime:
    def __init__(
        self,
        state_repo: WorkerStateRepository,
        *,
        worker_id: str,
        vu_type: type[VU],
        http_base_url: str = "",
        metric_id: str | None = None,
        idle_sleep_s: float = 0.05,
    ) -> None:
        self._state_repo = state_repo
        self._worker_id = worker_id
        self._vu_type = vu_type
        self._http_base_url = http_base_url
        self._metric_id = metric_id or f"worker:{worker_id}"
        self._idle_sleep_s = max(0.01, idle_sleep_s)

    async def run_user(self, user_id: str) -> None:
        http = WorkerVUHttpClient(base_url=self._http_base_url)
        resources = WorkerVUResources(self._state_repo)
        vu = self._vu_type(
            user_id=user_id,
            worker_id=self._worker_id,
            http=http,
            resources=resources,
        )

        completed_steps: set[str] = set()
        next_allowed_at: dict[str, float] = {}
        rng = random.Random(f"{self._worker_id}:{user_id}")
        steps = bind_steps(vu)

        try:
            await vu.on_start()
            while True:
                now = time.monotonic()
                eligible = []
                nearest_ready_at: float | None = None

                for bound_step in steps:
                    spec = bound_step.spec
                    if any(required not in completed_steps for required in spec.requires):
                        continue
                    ready_at = next_allowed_at.get(spec.step_name, 0.0)
                    if ready_at <= now:
                        eligible.append(bound_step)
                    elif nearest_ready_at is None or ready_at < nearest_ready_at:
                        nearest_ready_at = ready_at

                if not eligible:
                    if nearest_ready_at is None:
                        await asyncio.sleep(self._idle_sleep_s)
                    else:
                        await asyncio.sleep(max(self._idle_sleep_s, nearest_ready_at - now))
                    continue

                chosen = rng.choices(
                    eligible,
                    weights=[item.spec.weight for item in eligible],
                    k=1,
                )[0]
                await self._execute_step(
                    user_id=user_id,
                    completed_steps=completed_steps,
                    next_allowed_at=next_allowed_at,
                    bound_step=chosen,
                )
        except asyncio.CancelledError:
            raise
        finally:
            try:
                await vu.on_stop()
            finally:
                await http.close()

    async def _execute_step(
        self,
        *,
        user_id: str,
        completed_steps: set[str],
        next_allowed_at: dict[str, float],
        bound_step: Any,
    ) -> None:
        spec = bound_step.spec
        started_at = time.perf_counter()
        status_code: int | None = None
        error_text: str | None = None
        success = False
        cancelled = False

        try:
            if spec.timeout_s is None:
                result = await bound_step.call()
            else:
                async with asyncio.timeout(spec.timeout_s):
                    result = await bound_step.call()
            status_code = _extract_status_code(result)
            success = status_code is None or status_code < 400
            if success:
                completed_steps.add(spec.step_name)
            else:
                error_text = f"http_status_{status_code}"
        except asyncio.CancelledError:
            cancelled = True
            raise
        except Exception as exc:  # noqa: BLE001
            error_text = f"{type(exc).__name__}: {exc}"
            logger.debug(
                "VU step failed (worker_id=%s, user_id=%s, step=%s)",
                self._worker_id,
                user_id,
                spec.step_name,
                exc_info=True,
            )
        finally:
            elapsed_ms = round((time.perf_counter() - started_at) * 1000, 3)
            if spec.every_s is not None:
                next_allowed_at[spec.step_name] = time.monotonic() + spec.every_s
            else:
                next_allowed_at[spec.step_name] = 0.0
            if not cancelled:
                event = {
                    "ts_ms": int(time.time() * 1000),
                    "worker_id": self._worker_id,
                    "user_id": user_id,
                    "step": spec.step_name,
                    "latency_ms": elapsed_ms,
                }
                if status_code is not None:
                    event["status_code"] = status_code
                if not success:
                    event["error"] = error_text or "step_error"
                await self._publish_metric_event(event)

    async def _publish_metric_event(self, event: dict[str, Any]) -> None:
        try:
            await self._state_repo.append_metric_event(self._metric_id, event)
        except Exception:  # noqa: BLE001
            logger.exception(
                "failed to publish worker metric (worker_id=%s, metric_id=%s)",
                self._worker_id,
                self._metric_id,
            )


def load_vu_type(import_path: str) -> type[VU]:
    normalized = (import_path or "").strip()
    if not normalized:
        normalized = DEFAULT_SCENARIO_IMPORT

    module_name, sep, attr_name = normalized.partition(":")
    if not sep or not module_name or not attr_name:
        raise ValueError(
            "scenario import path must use format `module.path:ClassName`"
        )

    module = importlib.import_module(module_name)
    candidate = getattr(module, attr_name, None)
    if candidate is None:
        raise ValueError(f"scenario class `{attr_name}` not found in module `{module_name}`")
    if not inspect.isclass(candidate):
        raise ValueError(f"scenario target `{normalized}` must be a class")
    if not issubclass(candidate, VU):
        raise ValueError(f"scenario class `{normalized}` must inherit from VU")
    return candidate


def _extract_status_code(result: Any) -> int | None:
    status = getattr(result, "status", None)
    if status is None:
        return None
    try:
        return int(status)
    except (TypeError, ValueError):
        return None


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value
