from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol

_STEP_SPEC_ATTR = "__vikhry_step_spec__"
_RESOURCE_SPEC_ATTR = "__vikhry_resource_spec__"


class SupportsHTTP(Protocol):
    async def request(self, method: str, url: str, **kwargs: Any) -> Any: ...


class SupportsResources(Protocol):
    async def acquire(self, resource_name: str) -> dict[str, Any]: ...
    async def release(self, resource_name: str, resource_id: int | str) -> None: ...


@dataclass(slots=True, frozen=True)
class StepSpec:
    method_name: str
    step_name: str
    weight: float
    every_s: float | None
    requires: tuple[str, ...]
    timeout_s: float | None


@dataclass(slots=True, frozen=True)
class ResourceSpec:
    name: str
    function_name: str


@dataclass(slots=True)
class BoundStep:
    spec: StepSpec
    call: Callable[[], Awaitable[Any]]


class VU:
    def __init__(
        self,
        *,
        user_id: str,
        worker_id: str,
        http: SupportsHTTP,
        resources: SupportsResources,
    ) -> None:
        self.user_id = user_id
        self.worker_id = worker_id
        self.http = http
        self.resources = resources

    async def on_start(self) -> None:
        return None

    async def on_stop(self) -> None:
        return None


def step(
    *,
    name: str | None = None,
    weight: float = 1.0,
    every_s: float | None = None,
    requires: tuple[str, ...] = (),
    timeout_s: float | None = None,
) -> Callable[[Callable[..., Awaitable[Any]]], Callable[..., Awaitable[Any]]]:
    if weight <= 0:
        raise ValueError("step weight must be > 0")
    if every_s is not None and every_s <= 0:
        raise ValueError("step every_s must be > 0 when provided")
    if timeout_s is not None and timeout_s <= 0:
        raise ValueError("step timeout_s must be > 0 when provided")

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
                "timeout_s": timeout_s,
            },
        )
        return func

    return decorator


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
                    timeout_s=raw["timeout_s"],
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
