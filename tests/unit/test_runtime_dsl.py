from __future__ import annotations

import pytest

from vikhry.runtime import VU, bind_steps, collect_resource_factories, collect_vu_steps, resource, step


class _DummyHttp:
    async def request(self, method: str, url: str, **kwargs: object) -> object:
        _ = (method, url, kwargs)
        return None


class _DummyResources:
    async def acquire(self, resource_name: str) -> dict[str, object]:
        return {"resource_name": resource_name, "resource_id": "1"}

    async def release(self, resource_name: str, resource_id: int | str) -> None:
        _ = (resource_name, resource_id)


class _ExampleVU(VU):
    @step(weight=2.0)
    async def first(self) -> None:
        return None

    @step(name="second_step", every_s=1.5, requires=("first",), timeout_s=2.0)
    async def second(self) -> None:
        return None


def _make_vu(vu_type: type[VU]) -> VU:
    return vu_type(
        user_id="u1",
        worker_id="w1",
        http=_DummyHttp(),
        resources=_DummyResources(),
    )


def test_collect_vu_steps_exposes_step_metadata_spec() -> None:
    steps = collect_vu_steps(_ExampleVU)
    assert [item.step_name for item in steps] == ["first", "second_step"]
    assert steps[0].weight == 2.0
    assert steps[1].every_s == 1.5
    assert steps[1].requires == ("first",)
    assert steps[1].timeout_s == 2.0


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


def test_step_requires_async_function_spec() -> None:
    with pytest.raises(TypeError, match="async function"):

        @step()
        def sync_step(self) -> None:  # noqa: ANN001
            return None

