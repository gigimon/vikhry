from __future__ import annotations

import asyncio
import inspect
import logging
import re
import time
import traceback as traceback_module
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from functools import wraps
from typing import Any, Final

logger = logging.getLogger(__name__)

MetricEmitter = Callable[[dict[str, Any]], Awaitable[None]]

_UNSET: Final = object()
_UNKNOWN_STEP: Final = "__unknown__"
_UNKNOWN_STAGE: Final = "unknown"
_UNKNOWN_SOURCE: Final = "unknown"
_UNKNOWN_RESULT_CODE: Final = "UNKNOWN"
_UNKNOWN_RESULT_CATEGORY: Final = "unknown"
_MAX_RESULT_TOKEN_LENGTH: Final = 64
_MAX_ERROR_MESSAGE_LENGTH: Final = 256
_TOKEN_SANITIZE_PATTERN: Final = re.compile(r"[^A-Z0-9_:-]+")
_CATEGORY_SANITIZE_PATTERN: Final = re.compile(r"[^a-z0-9_:-]+")
_REQUIRED_FIELDS: Final[tuple[str, ...]] = (
    "name",
    "step",
    "status",
    "time",
    "source",
    "stage",
    "result_code",
    "result_category",
    "fatal",
)
_metric_emitter_var: ContextVar[MetricEmitter | None] = ContextVar(
    "vikhry_metric_emitter", default=None
)
_metric_step_var: ContextVar[str | None] = ContextVar("vikhry_metric_step", default=None)
_metric_stage_var: ContextVar[str | None] = ContextVar("vikhry_metric_stage", default=None)


@contextmanager
def metric_scope(
    *,
    emitter: MetricEmitter | None | object = _UNSET,
    step: str | None | object = _UNSET,
    stage: str | None | object = _UNSET,
) -> Iterator[None]:
    emitter_token: Token[MetricEmitter | None] | None = None
    step_token: Token[str | None] | None = None
    stage_token: Token[str | None] | None = None

    if emitter is not _UNSET:
        emitter_token = _metric_emitter_var.set(emitter)
    if step is not _UNSET:
        step_token = _metric_step_var.set(_normalize_metric_step(step))
    if stage is not _UNSET:
        stage_token = _metric_stage_var.set(_normalize_stage(stage))

    try:
        yield
    finally:
        if stage_token is not None:
            _metric_stage_var.reset(stage_token)
        if step_token is not None:
            _metric_step_var.reset(step_token)
        if emitter_token is not None:
            _metric_emitter_var.reset(emitter_token)


async def emit_metric(
    *,
    name: str,
    status: bool,
    time: float,
    source: str,
    stage: str | None = None,
    result_code: str,
    result_category: str,
    fatal: bool = False,
    step: str | None = None,
    error_type: str | None = None,
    error_message: str | None = None,
    traceback: str | None = None,
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
        source=source,
        stage=stage if stage is not None else _metric_stage_var.get(),
        result_code=result_code,
        result_category=result_category,
        fatal=fatal,
        error_type=error_type,
        error_message=error_message,
        traceback=traceback,
        **fields,
    )
    await emitter(payload)
    return True


def metric(
    *,
    name: str | None = None,
    source: str = "custom",
    stage: str = "execute",
    success_result_code: str = "METRIC_OK",
    success_result_category: str = "ok",
    failure_result_code: str = "METRIC_EXCEPTION",
    failure_result_category: str = "exception",
    fatal: bool = False,
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
            except Exception as exc:
                await _safe_emit(
                    metric_name=name or func.__name__,
                    status=False,
                    elapsed_ms=(time.perf_counter() - started_at) * 1000,
                    source=source,
                    stage=stage,
                    result_code=failure_result_code,
                    result_category=failure_result_category,
                    fatal=fatal,
                    error_type=type(exc).__name__,
                    error_message=str(exc),
                    traceback=_format_traceback(exc),
                    fields=fields,
                )
                raise

            await _safe_emit(
                metric_name=name or func.__name__,
                status=True,
                elapsed_ms=(time.perf_counter() - started_at) * 1000,
                source=source,
                stage=stage,
                result_code=success_result_code,
                result_category=success_result_category,
                fatal=fatal,
                fields=fields,
            )
            return result

        return wrapped

    return decorator


def build_metric_payload(
    *,
    name: str,
    step: str | None,
    status: bool,
    time: float,
    source: str,
    stage: str | None,
    result_code: str,
    result_category: str,
    fatal: bool,
    error_type: str | None = None,
    error_message: str | None = None,
    traceback: str | None = None,
    **fields: Any,
) -> dict[str, Any]:
    for required_field in _REQUIRED_FIELDS:
        if required_field in fields:
            raise ValueError(f"metric field `{required_field}` is reserved")

    normalized_name = _normalize_metric_name(name)
    normalized_step = _normalize_metric_step(step)
    normalized_status = _normalize_metric_status(status)
    normalized_time = float(time)
    normalized_source = _normalize_source(source)
    normalized_stage = _normalize_stage(stage)
    normalized_result_code = normalize_result_code(result_code)
    normalized_result_category = _normalize_result_category(result_category)
    if normalized_time < 0:
        raise ValueError("metric time must be >= 0")

    payload: dict[str, Any] = {
        "name": normalized_name,
        "step": normalized_step,
        "status": normalized_status,
        "time": normalized_time,
        "source": normalized_source,
        "stage": normalized_stage,
        "result_code": normalized_result_code,
        "result_category": normalized_result_category,
        "fatal": bool(fatal),
    }
    if error_type is not None:
        payload["error_type"] = _normalize_error_type(error_type)
    if error_message is not None:
        payload["error_message"] = _normalize_error_message(error_message)
    if traceback is not None:
        payload["traceback"] = _normalize_traceback(traceback)
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
    source: str,
    stage: str,
    result_code: str,
    result_category: str,
    fatal: bool,
    error_type: str | None = None,
    error_message: str | None = None,
    traceback: str | None = None,
    fields: dict[str, Any],
) -> None:
    try:
        await emit_metric(
            name=metric_name,
            status=status,
            time=round(elapsed_ms, 3),
            source=source,
            stage=stage,
            result_code=result_code,
            result_category=result_category,
            fatal=fatal,
            error_type=error_type,
            error_message=error_message,
            traceback=traceback,
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


def _normalize_metric_status(status: bool) -> bool:
    if isinstance(status, bool):
        return status
    raise ValueError("metric status must be bool")


def _normalize_source(source: str) -> str:
    normalized = str(source).strip().lower()
    if not normalized:
        return _UNKNOWN_SOURCE
    return normalized


def _normalize_stage(stage: str | None | object) -> str:
    if stage is None:
        return _UNKNOWN_STAGE
    normalized = str(stage).strip().lower()
    if not normalized:
        return _UNKNOWN_STAGE
    return normalized


def normalize_result_code(value: object) -> str:
    raw = str(value or "").strip().upper()
    if not raw:
        return _UNKNOWN_RESULT_CODE
    sanitized = _TOKEN_SANITIZE_PATTERN.sub("_", raw).strip("_")
    if not sanitized:
        return _UNKNOWN_RESULT_CODE
    return sanitized[:_MAX_RESULT_TOKEN_LENGTH]


def _normalize_result_category(value: object) -> str:
    raw = str(value or "").strip().lower()
    if not raw:
        return _UNKNOWN_RESULT_CATEGORY
    sanitized = _CATEGORY_SANITIZE_PATTERN.sub("_", raw).strip("_")
    if not sanitized:
        return _UNKNOWN_RESULT_CATEGORY
    return sanitized[:_MAX_RESULT_TOKEN_LENGTH]


def _normalize_error_type(value: object) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        return "UnknownError"
    return normalized[:_MAX_RESULT_TOKEN_LENGTH]


def _normalize_error_message(value: object) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        return ""
    return normalized[:_MAX_ERROR_MESSAGE_LENGTH]


def _normalize_traceback(value: object) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        return ""
    return normalized


def exception_fields(exc: BaseException) -> dict[str, str]:
    return {
        "error_type": type(exc).__name__,
        "error_message": _normalize_error_message(str(exc)),
        "traceback": _format_traceback(exc),
    }


def _format_traceback(exc: BaseException) -> str:
    return _normalize_traceback(
        "".join(traceback_module.format_exception(type(exc), exc, exc.__traceback__))
    )
