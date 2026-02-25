from dataclasses import asdict
from typing import Any

import orjson
from pydantic import ValidationError
from robyn import Request, Response, Robyn
from robyn.ws import WebSocketDisconnect

from vikhry.orchestrator.models.api import ChangeUsersRequest, StartTestRequest
from vikhry.orchestrator.models.resource import (
    CreateResourceRequest,
    EnsureResourceCountRequest,
)
from vikhry.orchestrator.services.lifecycle_service import (
    InvalidStateTransitionError,
    LifecycleService,
)
from vikhry.orchestrator.services.metrics_service import MetricsService
from vikhry.orchestrator.services.resource_service import ResourceService
from vikhry.orchestrator.services.worker_presence import (
    NoAliveWorkersError,
    WorkerPresenceService,
)


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
    lifecycle_service: LifecycleService,
    worker_presence: WorkerPresenceService,
    resource_service: ResourceService,
    metrics_service: MetricsService,
) -> None:
    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/ready")
    async def ready() -> dict[str, str | bool | int]:
        snapshot = await lifecycle_service.state_snapshot()
        alive_workers = worker_presence.cached_alive_workers()
        if not alive_workers and worker_presence.last_scan_ts() is None:
            alive_workers = await worker_presence.refresh_cache()
        return {
            "ready": await lifecycle_service.is_ready(),
            "state": snapshot["state"],
            "epoch": snapshot["epoch"],
            "alive_workers": len(alive_workers),
            "workers": alive_workers,
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
            model = StartTestRequest.model_validate(payload)
            result = await lifecycle_service.start_test(model.target_users)
            return asdict(result)
        except Exception as exc:  # noqa: BLE001
            return _exception_to_response(exc)

    @app.post("/change_users")
    async def change_users(request: Request) -> dict[str, object] | Response:
        try:
            payload = _parse_json_object(request)
            if "users" in payload and "target_users" not in payload:
                payload["target_users"] = payload.pop("users")
            model = ChangeUsersRequest.model_validate(payload)
            result = await lifecycle_service.change_users(model.target_users)
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
        raw_value = query.get(key)
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
