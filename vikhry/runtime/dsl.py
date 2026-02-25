from __future__ import annotations

import inspect
import random
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from vikhry.runtime.http import ReqwestClient, SupportsHTTP, close_http_client, resolve_http_client
from vikhry.runtime.resources import SupportsResources

_STEP_SPEC_ATTR = "__vikhry_step_spec__"
_RESOURCE_SPEC_ATTR = "__vikhry_resource_spec__"
EverySpec = float | Callable[[], float] | None


@dataclass(slots=True, frozen=True)
class StepSpec:
    method_name: str
    step_name: str
    weight: float
    every_s: EverySpec
    requires: tuple[str, ...]
    timeout: float | None


@dataclass(slots=True, frozen=True)
class ResourceSpec:
    name: str
    function_name: str


@dataclass(slots=True)
class BoundStep:
    spec: StepSpec
    call: Callable[[], Awaitable[Any]]


class VU:
    http = ReqwestClient()

    def __init__(
        self,
        *,
        user_id: str,
        worker_id: str,
        resources: SupportsResources,
        http_base_url: str = "",
    ) -> None:
        self.user_id = user_id
        self.worker_id = worker_id
        self.resources = resources
        self._http_base_url = http_base_url
        self._http_client: SupportsHTTP | None = None

    async def on_init(self, **_kwargs: Any) -> None:
        self.ensure_http_client()

    async def on_start(self) -> None:
        return None

    async def on_stop(self) -> None:
        return None

    async def close(self) -> None:
        await close_http_client(self._http_client)

    def ensure_http_client(self) -> SupportsHTTP:
        if self._http_client is not None:
            return self._http_client

        class_http_spec = getattr(type(self), "http", ReqwestClient())
        client = resolve_http_client(class_http_spec, base_url=self._http_base_url)
        self._http_client = client
        self.http = client
        return client


def step(
    *,
    name: str | None = None,
    weight: float = 1.0,
    every_s: EverySpec = None,
    requires: tuple[str, ...] = (),
    timeout: float | None = None,
) -> Callable[[Callable[..., Awaitable[Any]]], Callable[..., Awaitable[Any]]]:
    if weight <= 0:
        raise ValueError("step weight must be > 0")
    if every_s is not None and not callable(every_s):
        _validate_every_delay(float(every_s))
    if timeout is not None and timeout <= 0:
        raise ValueError("step timeout must be > 0 when provided")

    def decorator(func: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
        if not inspect.iscoroutinefunction(func):
            raise TypeError("step target must be an async function")
        setattr(
            func,
            _STEP_SPEC_ATTR,
            {
                "name": name,
                "weight": float(weight),
                "every_s": every_s,
                "requires": tuple(str(item) for item in requires),
                "timeout": timeout,
            },
        )
        return func

    return decorator


def between(min_s: float, max_s: float) -> Callable[[], float]:
    min_value = float(min_s)
    max_value = float(max_s)
    if min_value <= 0:
        raise ValueError("between min must be > 0")
    if max_value < min_value:
        raise ValueError("between max must be >= min")

    def _next_delay() -> float:
        return random.uniform(min_value, max_value)

    return _next_delay


def resource(*, name: str) -> Callable[[Callable[..., Awaitable[Any]]], Callable[..., Awaitable[Any]]]:
    normalized = name.strip()
    if not normalized:
        raise ValueError("resource name must not be empty")

    def decorator(func: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
        if not inspect.iscoroutinefunction(func):
            raise TypeError("resource target must be an async function")
        setattr(func, _RESOURCE_SPEC_ATTR, {"name": normalized})
        return func

    return decorator


def collect_vu_steps(vu_type: type[VU]) -> tuple[StepSpec, ...]:
    if not issubclass(vu_type, VU):
        raise TypeError("vu_type must inherit from VU")

    step_specs: list[StepSpec] = []
    seen_step_names: set[str] = set()

    for cls in reversed(vu_type.mro()):
        if not issubclass(cls, VU):
            continue
        for method_name, attr in cls.__dict__.items():
            raw = getattr(attr, _STEP_SPEC_ATTR, None)
            if raw is None:
                continue
            # Skip overridden base methods.
            if getattr(vu_type, method_name, None) is not attr:
                continue

            step_name = str(raw.get("name") or method_name)
            if step_name in seen_step_names:
                raise ValueError(f"duplicate step name detected: {step_name}")
            seen_step_names.add(step_name)
            step_specs.append(
                StepSpec(
                    method_name=method_name,
                    step_name=step_name,
                    weight=float(raw["weight"]),
                    every_s=raw["every_s"],
                    requires=tuple(raw["requires"]),
                    timeout=raw["timeout"],
                )
            )

    return tuple(step_specs)


def bind_steps(vu: VU) -> tuple[BoundStep, ...]:
    specs = collect_vu_steps(type(vu))
    bound: list[BoundStep] = []
    for spec in specs:
        target = getattr(vu, spec.method_name, None)
        if target is None:
            continue
        if not callable(target):
            raise TypeError(f"step {spec.method_name} is not callable")
        bound.append(BoundStep(spec=spec, call=target))
    return tuple(bound)


def collect_resource_factories(namespace: dict[str, Any]) -> dict[str, Callable[..., Awaitable[Any]]]:
    factories: dict[str, Callable[..., Awaitable[Any]]] = {}
    for name, value in namespace.items():
        raw = getattr(value, _RESOURCE_SPEC_ATTR, None)
        if raw is None:
            continue
        resource_name = str(raw.get("name", "")).strip()
        if not resource_name:
            continue
        if resource_name in factories:
            raise ValueError(f"duplicate resource factory for name={resource_name}")
        factories[resource_name] = value
    return factories


def resolve_every_delay(every_s: EverySpec) -> float:
    if every_s is None:
        return 0.0
    if callable(every_s):
        return _validate_every_delay(float(every_s()))
    return _validate_every_delay(float(every_s))


def _validate_every_delay(value: float) -> float:
    if value <= 0:
        raise ValueError("every_s must resolve to value > 0")
    return value
