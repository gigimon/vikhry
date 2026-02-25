from __future__ import annotations

from typing import Any

import orjson
from redis.asyncio import Redis
from redis.asyncio.client import PubSub

from vikhry.orchestrator.models.command import CommandEnvelope
from vikhry.orchestrator.models.worker import WorkerHealthStatus


class WorkerStateRepository:
    def __init__(self, redis_client: Redis) -> None:
        self._redis = redis_client

    @staticmethod
    def worker_status_key(worker_id: str) -> str:
        return f"worker:{worker_id}:status"

    @staticmethod
    def worker_users_key(worker_id: str) -> str:
        return f"worker:{worker_id}:users"

    @staticmethod
    def worker_command_channel(worker_id: str) -> str:
        return f"worker:{worker_id}:commands"

    @staticmethod
    def resource_key(resource_name: str, resource_id: int | str) -> str:
        return f"resource:{resource_name}:{resource_id}"

    @staticmethod
    def resource_available_key(resource_name: str) -> str:
        return f"resource:{resource_name}:available"

    @staticmethod
    def resource_loaded_count_key(resource_name: str) -> str:
        return f"resource:{resource_name}:pool_loaded_count"

    @staticmethod
    def metric_stream_key(metric_id: str) -> str:
        return f"metric:{metric_id}"

    async def register_worker(self, worker_id: str) -> None:
        await self._redis.sadd("workers", worker_id)

    async def unregister_worker(self, worker_id: str) -> None:
        pipeline = self._redis.pipeline()
        pipeline.srem("workers", worker_id)
        pipeline.delete(self.worker_status_key(worker_id))
        pipeline.delete(self.worker_users_key(worker_id))
        await pipeline.execute()

    async def set_worker_health(
        self,
        worker_id: str,
        *,
        status: WorkerHealthStatus,
        last_heartbeat: int,
    ) -> None:
        await self._redis.hset(
            self.worker_status_key(worker_id),
            mapping={
                "status": status.value,
                "last_heartbeat": str(last_heartbeat),
            },
        )

    async def subscribe_commands(self, worker_id: str) -> PubSub:
        pubsub = self._redis.pubsub(ignore_subscribe_messages=True)
        await pubsub.subscribe(self.worker_command_channel(worker_id))
        return pubsub

    async def append_metric_event(self, metric_id: str, event: dict[str, Any]) -> str:
        await self._redis.sadd("metrics", metric_id)
        event_id = await self._redis.xadd(
            self.metric_stream_key(metric_id),
            {"data": orjson.dumps(event).decode("utf-8")},
        )
        return str(event_id)

    async def acquire_resource_data(self, resource_name: str) -> dict[str, Any] | None:
        await self._ensure_resource_pool_synced(resource_name)
        resource_id = await self._redis.spop(self.resource_available_key(resource_name))
        if resource_id is None:
            return None

        payload = await self._redis.get(self.resource_key(resource_name, resource_id))
        if payload is None:
            return None
        parsed = orjson.loads(payload)
        if not isinstance(parsed, dict):
            raise TypeError("Resource payload must be JSON object")
        parsed.setdefault("resource_id", str(resource_id))
        return parsed

    async def release_resource(self, resource_name: str, resource_id: int | str) -> None:
        await self._redis.sadd(self.resource_available_key(resource_name), str(resource_id))

    async def _ensure_resource_pool_synced(self, resource_name: str) -> None:
        raw_total = await self._redis.hget("resources", resource_name)
        total = int(raw_total) if raw_total is not None else 0
        if total <= 0:
            return

        raw_loaded = await self._redis.get(self.resource_loaded_count_key(resource_name))
        loaded = int(raw_loaded) if raw_loaded is not None else 0
        if total <= loaded:
            return

        new_ids = [str(resource_id) for resource_id in range(loaded + 1, total + 1)]
        if new_ids:
            await self._redis.sadd(self.resource_available_key(resource_name), *new_ids)
        await self._redis.set(self.resource_loaded_count_key(resource_name), str(total))

    @staticmethod
    def decode_command(raw: bytes | bytearray | memoryview | str) -> CommandEnvelope:
        return CommandEnvelope.from_json_bytes(raw)
