from __future__ import annotations

from typing import Any, Protocol


class SupportsResources(Protocol):
    async def acquire(self, resource_name: str) -> dict[str, Any]: ...
    async def release(self, resource_name: str, resource_id: int | str) -> None: ...

