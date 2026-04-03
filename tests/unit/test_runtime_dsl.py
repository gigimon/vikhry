from __future__ import annotations

import pytest

from vikhry.runtime import (
    ProbeSpec,
    ReqwestClient,
    VU,
    between,
    bind_steps,
    collect_probe_specs,
    collect_resource_factories,
    collect_vu_steps,
    probe,
    resource,
    step,
)
from vikhry.runtime.dsl import resolve_every_delay


class _DummyResources:
    async def acquire(self, resource_name: str) -> dict[str, object]:
        return {"resource_name": resource_name, "resource_id": "1"}

    async def release(self, resource_name: str, resource_id: int | str) -> None:
        _ = (resource_name, resource_id)


class _FactoryHttp:
    def __init__(self) -> None:
        self.calls = 0

    def create(self, *, base_url: str = "") -> "_FactoryHttpClient":
        self.calls += 1
        return _FactoryHttpClient(base_url)


class _FactoryHttpClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url

    async def request(self, method: str, url: str, **kwargs: object) -> object:
        _ = (method, url, kwargs)
        return None

    async def close(self) -> None:
        return None


class _ExampleVU(VU):
    @step(weight=2.0)
    async def first(self) -> None:
        return None

    @step(
        name="second_step",
        every_s=1.5,
        requires=("first",),
        timeout=2.0,
        lane="pages",
        priority=7,
    )
    async def second(self) -> None:
        return None


class _FactoryVU(VU):
    http = _FactoryHttp()


class _ReqwestFactoryVU(VU):
    http = ReqwestClient(timeout=5)

    async def on_init(self, base_url: str) -> None:
        self.http = self.http(base_url=base_url)


class _BaseInitVU(VU):
    http = ReqwestClient(timeout=5)


@probe(name="db_health", every_s=2.5, timeout=1.0)
async def _probe_db_health() -> int:
    return 1


@probe(name="shared", every_s=1.0)
async def _first_shared_probe() -> int:
    return 1


@probe(name="shared", every_s=2.0)
async def _second_shared_probe() -> int:
    return 2


def _make_vu(vu_type: type[VU]) -> VU:
    return vu_type(
        user_id="u1",
        worker_id="w1",
        resources=_DummyResources(),
        http_base_url="http://localhost:8000",
    )


def test_collect_vu_steps_exposes_step_metadata_spec() -> None:
    steps = collect_vu_steps(_ExampleVU)
    assert [item.step_name for item in steps] == ["first", "second_step"]
    assert steps[0].weight == 2.0
    assert steps[0].strategy_kwargs == {}
    assert steps[1].every_s == 1.5
    assert steps[1].requires == ("first",)
    assert steps[1].timeout == 2.0
    assert steps[1].strategy_kwargs == {"lane": "pages", "priority": 7}


def test_bind_steps_returns_bound_coroutines_spec() -> None:
    vu = _make_vu(_ExampleVU)
    steps = bind_steps(vu)
    assert [item.spec.step_name for item in steps] == ["first", "second_step"]
    for item in steps:
        assert callable(item.call)


def test_duplicate_step_names_raise_spec() -> None:
    class _DuplicateNamesVU(VU):
        @step(name="same")
        async def a(self) -> None:
            return None

        @step(name="same")
        async def b(self) -> None:
            return None

    with pytest.raises(ValueError, match="duplicate step name"):
        collect_vu_steps(_DuplicateNamesVU)


def test_resource_decorator_registration_spec() -> None:
    @resource(name="users")
    async def make_user(*_args: object) -> dict[str, object]:
        return {"resource_id": "1"}

    factories = collect_resource_factories({"make_user": make_user})
    assert list(factories) == ["users"]
    assert factories["users"] is make_user


def test_probe_decorator_registration_spec() -> None:
    specs = collect_probe_specs({"_probe_db_health": _probe_db_health})
    assert specs == (
        ProbeSpec(
            name="db_health",
            function_name="_probe_db_health",
            every_s=2.5,
            timeout=1.0,
        ),
    )


def test_duplicate_probe_names_raise_spec() -> None:
    with pytest.raises(ValueError, match="duplicate probe name"):
        collect_probe_specs(
            {
                "_first_shared_probe": _first_shared_probe,
                "_second_shared_probe": _second_shared_probe,
            }
        )


def test_collect_probe_specs_rejects_nested_functions_spec() -> None:
    def _build_probe():
        @probe(name="nested", every_s=1.0)
        async def nested_probe() -> int:
            return 1

        return nested_probe

    nested_probe = _build_probe()

    with pytest.raises(TypeError, match="module-level async function"):
        collect_probe_specs({"nested_probe": nested_probe})


def test_step_requires_async_function_spec() -> None:
    with pytest.raises(TypeError, match="async function"):

        @step()
        def sync_step(self) -> None:  # noqa: ANN001
            return None


def test_probe_requires_async_function_spec() -> None:
    with pytest.raises(TypeError, match="async function"):

        @probe(name="sync_probe", every_s=1.0)
        def sync_probe() -> None:
            return None


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"name": " ", "every_s": 1.0}, "probe name must not be empty"),
        ({"name": "probe", "every_s": None}, "probe every_s must be provided"),
        ({"name": "probe", "every_s": 0.0}, "every_s must resolve to value > 0"),
        ({"name": "probe", "every_s": 1.0, "timeout": 0.0}, "probe timeout must be > 0"),
    ],
)
def test_probe_validation_spec(kwargs: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        probe(**kwargs)


def test_between_returns_delay_in_range_spec() -> None:
    callback = between(0.1, 0.2)
    values = [callback() for _ in range(100)]
    assert all(0.1 <= value <= 0.2 for value in values)


def test_resolve_every_delay_accepts_callback_spec() -> None:
    delay = resolve_every_delay(lambda: 0.3)
    assert delay == 0.3


@pytest.mark.asyncio
async def test_vu_on_init_materializes_http_client_spec() -> None:
    vu = _FactoryVU(
        user_id="u1",
        worker_id="w1",
        resources=_DummyResources(),
        http_base_url="http://localhost:8000",
    )
    _FactoryVU.http.calls = 0
    await vu.on_init()
    try:
        assert callable(getattr(vu.http, "request", None))
        assert vu.http.base_url == "http://localhost:8000"
        assert _FactoryVU.http.calls == 1
    finally:
        await vu.close()


@pytest.mark.asyncio
async def test_vu_on_init_allows_callable_http_factory_spec() -> None:
    vu = _ReqwestFactoryVU(
        user_id="u1",
        worker_id="w1",
        resources=_DummyResources(),
        http_base_url="",
    )
    await vu.on_init(base_url="http://localhost:8000")
    try:
        client = vu.ensure_http_client()
        assert callable(getattr(client, "request", None))
        assert vu.http.base_url == "http://localhost:8000"
    finally:
        await vu.close()


@pytest.mark.asyncio
async def test_base_vu_on_init_accepts_base_url_spec() -> None:
    vu = _BaseInitVU(
        user_id="u1",
        worker_id="w1",
        resources=_DummyResources(),
        http_base_url="",
    )
    await vu.on_init(base_url="http://localhost:8000")
    try:
        assert callable(getattr(vu.http, "request", None))
        assert vu.http.base_url == "http://localhost:8000"
    finally:
        await vu.close()
