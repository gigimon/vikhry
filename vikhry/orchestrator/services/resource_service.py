from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from vikhry.orchestrator.models.resource import (
    CreateResourceResult,
    EnsureResourceCountResult,
)
from vikhry.orchestrator.redis_repo.state_repo import TestStateRepository

logger = logging.getLogger(__name__)


class ResourceService:
    def __init__(
        self,
        state_repo: TestStateRepository,
        scenario_resource_names: list[str] | None = None,
        default_prepare_counts: dict[str, int] | None = None,
        resource_factories: dict[str, Callable[..., Awaitable[Any]]] | None = None,
    ) -> None:
        self._state_repo = state_repo
        self._scenario_resource_names = sorted(set(scenario_resource_names or []))
        self._default_prepare_counts = default_prepare_counts or {}
        self._resource_factories = resource_factories or {}

    async def prepare_for_start(self, target_users: int) -> dict[str, Any]:
        logger.info(
            "prepare_for_start target_users=%s scenario_resources=%s mode=manual",
            target_users,
            self._scenario_resource_names,
        )
        created: dict[str, int] = {}
        for resource_name, desired_count in self._default_prepare_counts.items():
            if desired_count < 0:
                continue
            result = await self.ensure_resource_count(
                resource_name=resource_name,
                target_count=desired_count,
                payload={
                    "source": "preparing",
                },
            )
            created[result.resource_name] = result.created_count
        return {
            "created": created,
            "target_users": target_users,
            "scenario_resources": list(self._scenario_resource_names),
            "mode": "manual",
        }

    async def ensure_resource_count(
        self,
        resource_name: str,
        target_count: int,
        payload: dict[str, Any] | None = None,
    ) -> EnsureResourceCountResult:
        if target_count < 0:
            raise ValueError("target_count must be >= 0")

        counters = await self._state_repo.list_resource_counters()
        existing_count = counters.get(resource_name, 0)
        count_to_create = max(0, target_count - existing_count)

        created_resource_ids: list[str] = []
        if count_to_create > 0:
            result = await self.create_resources(
                resource_name=resource_name,
                count=count_to_create,
                payload={
                    **(payload or {}),
                    "source": (payload or {}).get("source", "ensure_resource_count"),
                    "target_count": target_count,
                    "existing_count": existing_count,
                },
            )
            created_resource_ids = result.resource_ids

        current_count = existing_count + count_to_create
        logger.info(
            "ensure_resource_count resource_name=%s existing_count=%s target_count=%s created_count=%s current_count=%s",
            resource_name,
            existing_count,
            target_count,
            count_to_create,
            current_count,
        )
        return EnsureResourceCountResult(
            resource_name=resource_name,
            target_count=target_count,
            existing_count=existing_count,
            created_count=count_to_create,
            current_count=current_count,
            created_resource_ids=created_resource_ids,
        )

    async def create_resources(
        self,
        resource_name: str,
        count: int,
        payload: dict[str, Any] | None = None,
    ) -> CreateResourceResult:
        payload = payload or {}
        resource_ids: list[str] = []
        created_at = self._now_ts()
        factory = self._resource_factories.get(resource_name)

        for _ in range(count):
            next_id = await self._state_repo.increment_resource_counter(resource_name, delta=1)
            resource_id = str(next_id)

            factory_fields: dict[str, Any] = {}
            if factory is not None:
                try:
                    factory_fields = await factory(resource_id, None)
                    if not isinstance(factory_fields, dict):
                        logger.warning(
                            "resource factory for %s returned non-dict (%s), ignoring",
                            resource_name,
                            type(factory_fields).__name__,
                        )
                        factory_fields = {}
                except Exception:  # noqa: BLE001
                    logger.exception(
                        "resource factory for %s raised on resource_id=%s",
                        resource_name,
                        resource_id,
                    )

            await self._state_repo.set_resource_data(
                resource_name=resource_name,
                resource_id=resource_id,
                payload={
                    **factory_fields,
                    **payload,
                    "resource_name": resource_name,
                    "resource_id": resource_id,
                    "created_at": created_at,
                },
            )
            resource_ids.append(resource_id)

        first_resource_id = resource_ids[0] if resource_ids else None
        last_resource_id = resource_ids[-1] if resource_ids else None
        logger.info(
            "create_resources resource_name=%s count=%s first_resource_id=%s last_resource_id=%s",
            resource_name,
            count,
            first_resource_id,
            last_resource_id,
        )
        return CreateResourceResult(
            resource_name=resource_name,
            count=count,
            resource_ids=resource_ids,
        )

    async def counters(self) -> dict[str, int]:
        return await self._state_repo.list_resource_counters()

    def scenario_resource_names(self) -> list[str]:
        return list(self._scenario_resource_names)

    @staticmethod
    def _now_ts() -> int:
        return int(time.time())
