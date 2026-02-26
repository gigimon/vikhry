from __future__ import annotations

import asyncio
import inspect
import logging
import time
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from functools import wraps
from typing import Any, Final, Literal

logger = logging.getLogger(__name__)

MetricStatus = bool | Literal["ok", "error", "success", "failed"]
MetricEmitter = Callable[[dict[str, Any]], Awaitable[None]]

_UNSET: Final = object()
_UNKNOWN_STEP: Final = "__unknown__"
_REQUIRED_FIELDS: Final[tuple[str, ...]] = ("name", "step", "status", "time")
_metric_emitter_var: ContextVar[MetricEmitter | None] = ContextVar(
    "vikhry_metric_emitter", default=None
)
_metric_step_var: ContextVar[str | None] = ContextVar("vikhry_metric_step", default=None)


@contextmanager
def metric_scope(
    *,
    emitter: MetricEmitter | None | object = _UNSET,
    step: str | None | object = _UNSET,
) -> Iterator[None]:
    emitter_token: Token[MetricEmitter | None] | None = None
    step_token: Token[str | None] | None = None

    if emitter is not _UNSET:
        emitter_token = _metric_emitter_var.set(emitter)
    if step is not _UNSET:
        step_token = _metric_step_var.set(_normalize_metric_step(step))

    try:
        yield
    finally:
        if step_token is not None:
            _metric_step_var.reset(step_token)
        if emitter_token is not None:
            _metric_emitter_var.reset(emitter_token)


async def emit_metric(
    *,
    name: str,
    status: MetricStatus,
    time: float,
    step: str | None = None,
    **fields: Any,
) -> bool:
    emitter = _metric_emitter_var.get()
    if emitter is None:
        return False

    payload = build_metric_payload(
        name=name,
        step=step if step is not None else _metric_step_var.get(),
        status=status,
        time=time,
        **fields,
    )
    await emitter(payload)
    return True


def metric(
    *,
    name: str | None = None,
    **fields: Any,
) -> Callable[[Callable[..., Awaitable[Any]]], Callable[..., Awaitable[Any]]]:
    def decorator(func: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
        if not inspect.iscoroutinefunction(func):
            raise TypeError("metric decorator target must be an async function")

        @wraps(func)
        async def wrapped(*args: Any, **kwargs: Any) -> Any:
            started_at = time.perf_counter()
            try:
                result = await func(*args, **kwargs)
            except asyncio.CancelledError:
                raise
            except Exception:
                await _safe_emit(
                    metric_name=name or func.__name__,
                    status=False,
                    elapsed_ms=(time.perf_counter() - started_at) * 1000,
                    fields=fields,
                )
                raise

            await _safe_emit(
                metric_name=name or func.__name__,
                status=True,
                elapsed_ms=(time.perf_counter() - started_at) * 1000,
                fields=fields,
            )
            return result

        return wrapped

    return decorator


def build_metric_payload(
    *,
    name: str,
    step: str | None,
    status: MetricStatus,
    time: float,
    **fields: Any,
) -> dict[str, Any]:
    for required_field in _REQUIRED_FIELDS:
        if required_field in fields:
            raise ValueError(f"metric field `{required_field}` is reserved")

    normalized_name = _normalize_metric_name(name)
    normalized_step = _normalize_metric_step(step)
    normalized_status = _normalize_metric_status(status)
    normalized_time = float(time)
    if normalized_time < 0:
        raise ValueError("metric time must be >= 0")

    payload: dict[str, Any] = {
        "name": normalized_name,
        "step": normalized_step,
        "status": normalized_status,
        "time": normalized_time,
    }
    payload.update(fields)
    return payload


def extract_status_code(result: Any) -> int | None:
    status = getattr(result, "status", None)
    if status is None:
        return None
    try:
        return int(status)
    except (TypeError, ValueError):
        return None


def is_success_status(status_code: int | None) -> bool:
    return status_code is None or status_code < 400


async def _safe_emit(
    *,
    metric_name: str,
    status: bool,
    elapsed_ms: float,
    fields: dict[str, Any],
) -> None:
    try:
        await emit_metric(
            name=metric_name,
            status=status,
            time=round(elapsed_ms, 3),
            **fields,
        )
    except Exception:  # noqa: BLE001
        logger.debug("failed to emit decorated metric", exc_info=True)


def _normalize_metric_name(name: str) -> str:
    normalized = str(name).strip()
    if not normalized:
        raise ValueError("metric name must not be empty")
    return normalized


def _normalize_metric_step(step: str | None | object) -> str:
    if step is None:
        return _UNKNOWN_STEP
    normalized = str(step).strip()
    if not normalized:
        return _UNKNOWN_STEP
    return normalized


def _normalize_metric_status(status: MetricStatus) -> bool:
    if isinstance(status, bool):
        return status
    normalized = str(status).strip().lower()
    if normalized in {"ok", "success"}:
        return True
    if normalized in {"error", "failed"}:
        return False
    raise ValueError("metric status must be bool or one of: ok,error,success,failed")

