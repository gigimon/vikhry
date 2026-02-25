from __future__ import annotations

import pytest

from vikhry.orchestrator.services.resource_service import ResourceService


class _FakeStateRepo:
    def __init__(self) -> None:
        self.counters: dict[str, int] = {"users": 2}
        self.payloads: dict[tuple[str, str], dict[str, object]] = {}

    async def list_resource_counters(self) -> dict[str, int]:
        return dict(self.counters)

    async def increment_resource_counter(self, resource_name: str, delta: int = 1) -> int:
        self.counters[resource_name] = self.counters.get(resource_name, 0) + delta
        return self.counters[resource_name]

    async def set_resource_data(
        self,
        resource_name: str,
        resource_id: int | str,
        payload: dict[str, object],
    ) -> None:
        self.payloads[(resource_name, str(resource_id))] = payload


@pytest.mark.asyncio
async def test_prepare_for_start_does_not_depend_on_target_users_spec() -> None:
    repo = _FakeStateRepo()
    service = ResourceService(
        state_repo=repo,  # type: ignore[arg-type]
        scenario_resource_names=["users", "products"],
    )

    result = await service.prepare_for_start(target_users=5)

    assert result["created"] == {}
    assert repo.counters["users"] == 2
    assert "products" not in repo.counters
    assert result["scenario_resources"] == ["products", "users"]


@pytest.mark.asyncio
async def test_ensure_resource_count_only_scales_up_spec() -> None:
    repo = _FakeStateRepo()
    service = ResourceService(
        state_repo=repo,  # type: ignore[arg-type]
    )

    up = await service.ensure_resource_count(resource_name="users", target_count=5)
    assert up.existing_count == 2
    assert up.created_count == 3
    assert up.current_count == 5
    assert len(up.created_resource_ids) == 3
    assert repo.counters["users"] == 5

    down = await service.ensure_resource_count(resource_name="users", target_count=1)
    assert down.existing_count == 5
    assert down.created_count == 0
    assert down.current_count == 5
    assert down.created_resource_ids == []
    assert repo.counters["users"] == 5
