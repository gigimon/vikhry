import asyncio
import logging
import math
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any

import orjson
from pydantic import ValidationError
from robyn import Request, Response, Robyn
from robyn.responses import serve_file, serve_html
from robyn.ws import WebSocketDisconnect

from vikhry.orchestrator.models.api import ChangeUsersRequest, StartTestRequest
from vikhry.orchestrator.models.resource import (
    CreateResourceRequest,
    EnsureResourceCountRequest,
)
from vikhry.orchestrator.models.worker import WorkerStatus
from vikhry.orchestrator.redis_repo.state_repo import TestStateRepository
from vikhry.orchestrator.services.lifecycle_service import (
    InvalidStateTransitionError,
    LifecycleService,
)
from vikhry.orchestrator.services.metrics_service import MetricsService
from vikhry.orchestrator.services.probe_service import ProbeService
from vikhry.orchestrator.services.resource_service import ResourceService
from vikhry.orchestrator.services.worker_presence import (
    NoAliveWorkersError,
    WorkerPresenceService,
)

logger = logging.getLogger(__name__)


class ApiError(Exception):
    def __init__(
        self,
        status: int,
        code: str,
        message: str,
        details: object | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.details = details


def register_routes(
    app: Robyn,
    state_repo: TestStateRepository,
    lifecycle_service: LifecycleService,
    worker_presence: WorkerPresenceService,
    resource_service: ResourceService,
    metrics_service: MetricsService,
    probe_service: ProbeService,
    scenario_on_init_spec: dict[str, object],
    ui_assets_dir: Path | None,
) -> None:
    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/ready")
    async def ready() -> dict[str, object]:
        snapshot = await lifecycle_service.state_snapshot()
        alive_workers = worker_presence.cached_alive_workers()
        if not alive_workers and worker_presence.last_scan_ts() is None:
            alive_workers = await worker_presence.refresh_cache()
        now_ts = worker_presence.now_ts()
        alive_statuses = (
            await asyncio.gather(*(state_repo.get_worker_status(worker_id) for worker_id in alive_workers))
            if alive_workers
            else []
        )
        return {
            "ready": await lifecycle_service.is_ready(),
            "state": snapshot["state"],
            "epoch": snapshot["epoch"],
            "alive_workers": len(alive_workers),
            "workers": alive_workers,
            "workers_status": [
                _ready_worker_payload(
                    worker_id=worker_id,
                    status=status,
                    now_ts=now_ts,
                )
                for worker_id, status in zip(alive_workers, alive_statuses, strict=True)
            ],
        }

    @app.post("/create_resource")
    async def create_resource(request: Request) -> dict[str, object] | Response:
        try:
            payload = _parse_json_object(request)
            if "resource_name" in payload and "name" not in payload:
                payload["name"] = payload.pop("resource_name")
            model = CreateResourceRequest.model_validate(payload)
            result = await resource_service.create_resources(
                resource_name=model.name,
                count=model.count,
                payload=model.payload,
            )
            return result.model_dump(mode="json")
        except Exception as exc:  # noqa: BLE001
            return _exception_to_response(exc)

    @app.post("/ensure_resource")
    async def ensure_resource(request: Request) -> dict[str, object] | Response:
        try:
            payload = _parse_json_object(request)
            if "resource_name" in payload and "name" not in payload:
                payload["name"] = payload.pop("resource_name")
            model = EnsureResourceCountRequest.model_validate(payload)
            result = await resource_service.ensure_resource_count(
                resource_name=model.name,
                target_count=model.count,
                payload=model.payload,
            )
            return result.model_dump(mode="json")
        except Exception as exc:  # noqa: BLE001
            return _exception_to_response(exc)

    @app.post("/start_test")
    async def start_test(request: Request) -> dict[str, object] | Response:
        try:
            payload = _parse_json_object(request)
            if "users" in payload and "target_users" not in payload:
                payload["target_users"] = payload.pop("users")
            if "params" in payload and "init_params" not in payload:
                payload["init_params"] = payload.pop("params")
            model = StartTestRequest.model_validate(payload)
            result = await lifecycle_service.start_test(
                model.target_users,
                model.init_params,
                spawn_interval_ms=model.spawn_interval_ms,
            )
            return asdict(result)
        except Exception as exc:  # noqa: BLE001
            return _exception_to_response(exc)

    @app.get("/scenario/on_init_params")
    async def scenario_on_init_params() -> dict[str, object]:
        return dict(scenario_on_init_spec)

    @app.post("/change_users")
    async def change_users(request: Request) -> dict[str, object] | Response:
        try:
            payload = _parse_json_object(request)
            if "users" in payload and "target_users" not in payload:
                payload["target_users"] = payload.pop("users")
            model = ChangeUsersRequest.model_validate(payload)
            result = await lifecycle_service.change_users(
                model.target_users,
                spawn_interval_ms=model.spawn_interval_ms,
            )
            return asdict(result)
        except Exception as exc:  # noqa: BLE001
            return _exception_to_response(exc)

    @app.post("/stop_test")
    async def stop_test(_: Request) -> dict[str, object] | Response:
        try:
            result = await lifecycle_service.stop_test()
            return asdict(result)
        except Exception as exc:  # noqa: BLE001
            return _exception_to_response(exc)

    @app.get("/metrics")
    async def metrics(request: Request) -> dict[str, object] | Response:
        try:
            count = _query_int(request, key="count", default=100, min_value=1, max_value=1000)
            metric_id = _query_value(request, "metric_id")
            include_events = _query_bool(request, key="include_events", default=True)
            result = await metrics_service.get_metrics(
                metric_id=metric_id,
                count=count,
                include_events=include_events,
            )
            return result
        except Exception as exc:  # noqa: BLE001
            return _exception_to_response(exc)

    @app.get("/metrics/history")
    async def metrics_history(request: Request) -> dict[str, object] | Response:
        try:
            range_id = _query_value(request, "range") or "all"
            now_ts = worker_presence.now_ts()
            from_ts = _resolve_history_from_ts(now_ts=now_ts, range_id=range_id)
            explicit_from_ts = _query_optional_int(
                request=request,
                key="from_ts",
                min_value=0,
                max_value=4_102_444_800,
            )
            if explicit_from_ts is not None:
                from_ts = explicit_from_ts
            started_at = time.perf_counter()
            result = await _build_metrics_history_response(
                state_repo=state_repo,
                now_ts=now_ts,
                from_ts=from_ts,
                range_id=range_id,
            )
            result["duration_ms"] = int((time.perf_counter() - started_at) * 1000)
            return result
        except Exception as exc:  # noqa: BLE001
            return _exception_to_response(exc)

    @app.get("/probes")
    async def probes(request: Request) -> dict[str, object] | Response:
        try:
            count = _query_int(request, key="count", default=20, min_value=0, max_value=1000)
            probe_name = _query_value(request, "probe_name")
            include_events = _query_bool(request, key="include_events", default=True)
            result = await probe_service.get_probes(
                probe_name=probe_name,
                count=count,
                include_events=include_events,
            )
            return result
        except Exception as exc:  # noqa: BLE001
            return _exception_to_response(exc)

    @app.get("/probes/history")
    async def probes_history(request: Request) -> dict[str, object] | Response:
        try:
            probe_name = _query_value(request, "probe_name")
            if probe_name is None:
                raise ApiError(
                    status=400,
                    code="validation_error",
                    message="Query param `probe_name` is required",
                )
            count = _query_int(request, key="count", default=100, min_value=0, max_value=1000)
            result = await probe_service.get_probe_history(
                probe_name=probe_name,
                count=count,
            )
            return result
        except Exception as exc:  # noqa: BLE001
            return _exception_to_response(exc)

    @app.get("/workers")
    async def workers() -> dict[str, object] | Response:
        try:
            return await _build_workers_response(state_repo=state_repo, worker_presence=worker_presence)
        except Exception as exc:  # noqa: BLE001
            return _exception_to_response(exc)

    @app.get("/resources")
    async def resources() -> dict[str, object] | Response:
        try:
            return await _build_resources_response(
                state_repo=state_repo,
                now_ts=worker_presence.now_ts(),
                declared_resource_names=resource_service.scenario_resource_names(),
            )
        except Exception as exc:  # noqa: BLE001
            return _exception_to_response(exc)

    @app.get("/resources/:resource_name/items")
    async def resource_items(request: Request) -> dict[str, object] | Response:
        try:
            resource_name = request.path_params.get("resource_name", "")
            if not resource_name:
                return _json_error_response("resource_name is required", status_code=400)
            counters = await state_repo.list_resource_counters()
            total = counters.get(resource_name, 0)
            items = await state_repo.list_resource_items(resource_name, total)
            return {
                "resource_name": resource_name,
                "total": total,
                "items": items,
            }
        except Exception as exc:  # noqa: BLE001
            return _exception_to_response(exc)

    @app.websocket("/ws/metrics")
    async def metrics_ws(websocket) -> None:
        subscriber_id, queue = await metrics_service.subscribe()
        try:
            initial = await metrics_service.get_metrics(count=100, include_events=False)
            await websocket.send_json({"type": "metrics_snapshot", "payload": initial})
            while True:
                item = await queue.get()
                await websocket.send_json(item)
        except WebSocketDisconnect:
            return None
        finally:
            await metrics_service.unsubscribe(subscriber_id)

    if ui_assets_dir is not None:
        _register_ui_routes(app=app, ui_assets_dir=ui_assets_dir)


def _register_ui_routes(app: Robyn, ui_assets_dir: Path) -> None:
    index_file = ui_assets_dir / "index.html"
    if not index_file.is_file():
        logger.warning("UI assets directory %s has no index.html; skipping UI routes", ui_assets_dir)
        return

    @app.get("/")
    async def ui_index() -> Response:
        return serve_html(str(index_file))

    for child in sorted(ui_assets_dir.iterdir(), key=lambda entry: entry.name):
        if child.name == "index.html":
            continue

        route = f"/{child.name}"
        if child.is_dir():
            app.serve_directory(route, str(child))
            continue

        app.get(route)(_static_file_handler(child))


def _static_file_handler(file_path: Path):
    async def handler() -> Response:
        return serve_file(str(file_path))

    return handler


async def _build_workers_response(
    state_repo: TestStateRepository,
    worker_presence: WorkerPresenceService,
) -> dict[str, object]:
    worker_ids = await state_repo.list_workers()
    now_ts = worker_presence.now_ts()
    if not worker_ids:
        return {
            "generated_at": now_ts,
            "count": 0,
            "workers": [],
        }

    statuses, worker_users, active_users_counts = await asyncio.gather(
        asyncio.gather(*(state_repo.get_worker_status(worker_id) for worker_id in worker_ids)),
        asyncio.gather(*(state_repo.list_worker_users(worker_id) for worker_id in worker_ids)),
        asyncio.gather(*(state_repo.count_worker_active_users(worker_id) for worker_id in worker_ids)),
    )
    return {
        "generated_at": now_ts,
        "count": len(worker_ids),
        "workers": [
            _worker_payload(
                worker_id=worker_id,
                status=status,
                users_count=len(users),
                active_users_count=active_users_count,
                now_ts=now_ts,
            )
            for worker_id, status, users, active_users_count in zip(
                worker_ids, statuses, worker_users, active_users_counts, strict=True
            )
        ],
    }


def _worker_payload(
    *,
    worker_id: str,
    status: WorkerStatus | None,
    users_count: int,
    active_users_count: int,
    now_ts: int,
) -> dict[str, object]:
    status_value: str | None = None
    last_heartbeat: int | None = None
    heartbeat_age_s: int | None = None
    cpu_percent: float | None = None
    process_ram_bytes: int | None = None
    total_ram_bytes: int | None = None
    if status is not None:
        status_value = status.status.value
        last_heartbeat = status.last_heartbeat
        heartbeat_age_s = max(0, now_ts - status.last_heartbeat)
        cpu_percent = status.cpu_percent
        process_ram_bytes = status.rss_bytes
        total_ram_bytes = status.total_ram_bytes
    return {
        "worker_id": worker_id,
        "status": status_value,
        "last_heartbeat": last_heartbeat,
        "heartbeat_age_s": heartbeat_age_s,
        "users_count": users_count,
        "active_users_count": active_users_count,
        "cpu_percent": cpu_percent,
        "process_ram_bytes": process_ram_bytes,
        "total_ram_bytes": total_ram_bytes,
    }


def _ready_worker_payload(
    *,
    worker_id: str,
    status: WorkerStatus | None,
    now_ts: int,
) -> dict[str, object]:
    payload = _worker_payload(
        worker_id=worker_id,
        status=status,
        users_count=0,
        active_users_count=0,
        now_ts=now_ts,
    )
    payload.pop("users_count", None)
    payload.pop("active_users_count", None)
    return payload


async def _build_resources_response(
    state_repo: TestStateRepository,
    now_ts: int,
    declared_resource_names: list[str] | None = None,
) -> dict[str, object]:
    counters = await state_repo.list_resource_counters()
    all_resource_names = sorted(set(counters) | set(declared_resource_names or []))
    resources = [
        {"resource_name": resource_name, "count": counters.get(resource_name, 0)}
        for resource_name in all_resource_names
    ]
    return {
        "generated_at": now_ts,
        "count": len(resources),
        "resources": resources,
    }


def _json_response(status: int, payload: dict[str, object]) -> Response:
    return Response(
        status,
        {"content-type": "application/json"},
        orjson.dumps(payload).decode("utf-8"),
    )


def _error_response(
    status: int,
    code: str,
    message: str,
    details: object | None = None,
) -> Response:
    payload: dict[str, object] = {"error": {"code": code, "message": message}}
    if details is not None:
        payload["error"]["details"] = details
    return _json_response(status=status, payload=payload)


def _exception_to_response(exc: Exception) -> Response:
    if isinstance(exc, ApiError):
        return _error_response(
            status=exc.status,
            code=exc.code,
            message=exc.message,
            details=exc.details,
        )
    if isinstance(exc, ValidationError):
        return _error_response(
            status=400,
            code="validation_error",
            message="Request validation failed",
            details=exc.errors(),
        )
    if isinstance(exc, InvalidStateTransitionError):
        return _error_response(
            status=409,
            code="invalid_state",
            message=str(exc),
            details={
                "action": exc.action,
                "current": exc.current.value,
                "expected": [state.value for state in exc.expected],
            },
        )
    if isinstance(exc, NoAliveWorkersError):
        return _error_response(
            status=409,
            code="no_alive_workers",
            message=str(exc),
        )
    if isinstance(exc, ValueError):
        return _error_response(
            status=400,
            code="bad_request",
            message=str(exc),
        )
    logger.exception("unhandled api exception", exc_info=(type(exc), exc, exc.__traceback__))
    return _error_response(
        status=500,
        code="internal_error",
        message="Unexpected server error",
    )


def _parse_json_object(request: Request) -> dict[str, Any]:
    try:
        payload = request.json()
    except Exception as exc:  # noqa: BLE001
        raise ApiError(status=400, code="invalid_json", message=str(exc)) from exc

    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise ApiError(
            status=400,
            code="invalid_json",
            message="JSON payload must be an object",
        )
    return dict(payload)


def _query_value(request: Request, key: str) -> str | None:
    query = request.query_params
    if query is None:
        return None
    raw_value: object | None = None
    if hasattr(query, "get"):
        raw_value = query.get(key, None)
    elif isinstance(query, dict):
        raw_value = query.get(key)
    if raw_value is None:
        return None
    if isinstance(raw_value, list):
        if not raw_value:
            return None
        raw_value = raw_value[0]
    return str(raw_value)


def _query_int(
    request: Request,
    key: str,
    default: int,
    min_value: int,
    max_value: int,
) -> int:
    raw_value = _query_value(request, key)
    if raw_value is None or raw_value == "":
        return default
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise ApiError(
            status=400,
            code="validation_error",
            message=f"Query param `{key}` must be integer",
        ) from exc
    if value < min_value or value > max_value:
        raise ApiError(
            status=400,
            code="validation_error",
            message=f"Query param `{key}` must be in [{min_value}, {max_value}]",
        )
    return value


def _query_bool(request: Request, key: str, default: bool) -> bool:
    raw_value = _query_value(request, key)
    if raw_value is None:
        return default
    normalized = raw_value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ApiError(
        status=400,
        code="validation_error",
        message=f"Query param `{key}` must be boolean",
    )


def _query_optional_int(
    *,
    request: Request,
    key: str,
    min_value: int,
    max_value: int,
) -> int | None:
    raw_value = _query_value(request, key)
    if raw_value is None or raw_value == "":
        return None
    try:
        value = int(raw_value)
    except ValueError as exc:
        raise ApiError(
            status=400,
            code="validation_error",
            message=f"Query param `{key}` must be integer",
        ) from exc
    if value < min_value or value > max_value:
        raise ApiError(
            status=400,
            code="validation_error",
            message=f"Query param `{key}` must be in [{min_value}, {max_value}]",
        )
    return value


def _resolve_history_from_ts(*, now_ts: int, range_id: str) -> int | None:
    window_by_range: dict[str, int | None] = {
        "5m": 5 * 60,
        "15m": 15 * 60,
        "30m": 30 * 60,
        "all": None,
    }
    if range_id not in window_by_range:
        raise ApiError(
            status=400,
            code="validation_error",
            message="Query param `range` must be one of: 5m, 15m, 30m, all",
        )
    window_s = window_by_range[range_id]
    if window_s is None:
        return None
    return max(0, now_ts - window_s)


def _parse_metric_event_second(event_id: str) -> int | None:
    raw_timestamp = event_id.split("-", maxsplit=1)[0]
    try:
        timestamp_ms = int(raw_timestamp)
    except ValueError:
        return None
    return max(0, int(timestamp_ms / 1000))


def _extract_latency_value(event_payload: dict[str, Any]) -> float | None:
    raw = event_payload.get("time")
    if raw is None:
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(value) or value < 0:
        return None
    return value


def _sorted_median(sorted_values: list[float]) -> float | None:
    if not sorted_values:
        return None
    size = len(sorted_values)
    middle = size // 2
    if size % 2:
        return sorted_values[middle]
    return (sorted_values[middle - 1] + sorted_values[middle]) / 2


def _sorted_percentile_nearest_rank(
    sorted_values: list[float],
    *,
    percentile: int,
) -> float | None:
    if not sorted_values:
        return None
    if percentile <= 0:
        return sorted_values[0]
    if percentile >= 100:
        return sorted_values[-1]
    rank = math.ceil((percentile / 100) * len(sorted_values))
    index = min(len(sorted_values) - 1, max(0, rank - 1))
    return sorted_values[index]


def _round_chart_number(value: float, digits: int = 3) -> float:
    return round(value, digits)


async def _read_metric_events_from_stream(
    *,
    state_repo: TestStateRepository,
    metric_id: str,
    from_ts: int | None,
    batch_size: int = 5000,
) -> list[dict[str, Any]]:
    if from_ts is None:
        start = "-"
    else:
        start = f"{from_ts * 1000}-0"

    events: list[dict[str, Any]] = []
    last_event_id: str | None = None
    while True:
        if last_event_id is None:
            chunk = await state_repo.read_metric_events(
                metric_id=metric_id,
                start=start,
                end="+",
                count=batch_size,
            )
        else:
            chunk = await state_repo.read_metric_events_after(
                metric_id=metric_id,
                after_event_id=last_event_id,
                count=batch_size,
            )

        if not chunk:
            break

        events.extend(chunk)
        last_event_id = chunk[-1]["event_id"]
        if len(chunk) < batch_size:
            break

    return events


async def _read_users_timeline_events_from_stream(
    *,
    state_repo: TestStateRepository,
    from_ts: int | None,
    batch_size: int = 5000,
) -> list[dict[str, Any]]:
    if from_ts is None:
        start = "-"
    else:
        start = f"{from_ts * 1000}-0"

    events: list[dict[str, Any]] = []
    last_event_id: str | None = None
    while True:
        if last_event_id is None:
            chunk = await state_repo.read_users_timeline_events(
                start=start,
                end="+",
                count=batch_size,
            )
        else:
            chunk = await state_repo.read_users_timeline_events_after(
                after_event_id=last_event_id,
                count=batch_size,
            )

        if not chunk:
            break

        events.extend(chunk)
        last_event_id = chunk[-1]["event_id"]
        if len(chunk) < batch_size:
            break

    return events


async def _build_metrics_history_response(
    *,
    state_repo: TestStateRepository,
    now_ts: int,
    from_ts: int | None,
    range_id: str,
) -> dict[str, object]:
    metric_ids = await state_repo.list_metrics()
    points: dict[int, dict[str, dict[str, Any]]] = {}
    users_timeline_by_ts: dict[int, int] = {}

    for metric_id in metric_ids:
        events = await _read_metric_events_from_stream(
            state_repo=state_repo,
            metric_id=metric_id,
            from_ts=from_ts,
        )
        for event in events:
            event_id = str(event.get("event_id", ""))
            ts = _parse_metric_event_second(event_id)
            if ts is None:
                continue

            metric_data_by_id = points.setdefault(ts, {})
            metric_data = metric_data_by_id.setdefault(
                metric_id,
                {
                    "requests": 0,
                    "latencies": [],
                },
            )
            metric_data["requests"] = int(metric_data["requests"]) + 1
            payload = event.get("data")
            if not isinstance(payload, dict):
                continue
            latency = _extract_latency_value(payload)
            if latency is None:
                continue
            metric_data["latencies"].append(latency)

    users_timeline_events = await _read_users_timeline_events_from_stream(
        state_repo=state_repo,
        from_ts=from_ts,
    )
    for event in users_timeline_events:
        event_id = str(event.get("event_id", ""))
        ts = _parse_metric_event_second(event_id)
        if ts is None:
            continue
        users_count = event.get("users_count")
        if isinstance(users_count, int):
            users_timeline_by_ts[ts] = max(0, users_count)

    series: list[dict[str, object]] = []
    all_timestamps = sorted(set(points.keys()) | set(users_timeline_by_ts.keys()))
    for ts in all_timestamps:
        metric_payload: dict[str, dict[str, object]] = {}
        metric_data_by_id = points.get(ts, {})
        for metric_id, metric_data in metric_data_by_id.items():
            requests = int(metric_data["requests"])
            latencies = sorted(float(value) for value in metric_data["latencies"])
            avg = _round_chart_number(sum(latencies) / len(latencies)) if latencies else None
            median = _sorted_median(latencies)
            p95 = _sorted_percentile_nearest_rank(latencies, percentile=95)
            p99 = _sorted_percentile_nearest_rank(latencies, percentile=99)
            metric_payload[metric_id] = {
                "rps": requests,
                "latency_avg_ms": avg,
                "latency_median_ms": _round_chart_number(median) if median is not None else None,
                "latency_p95_ms": _round_chart_number(p95) if p95 is not None else None,
                "latency_p99_ms": _round_chart_number(p99) if p99 is not None else None,
            }
        series.append(
            {
                "ts": ts,
                "users": users_timeline_by_ts.get(ts),
                "metrics": metric_payload,
            }
        )

    return {
        "generated_at": now_ts,
        "range": range_id,
        "from_ts": from_ts,
        "count": len(series),
        "points": series,
    }
