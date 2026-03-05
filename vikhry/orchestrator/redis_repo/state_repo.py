from __future__ import annotations

from typing import Any

import orjson
from redis.asyncio import Redis

from vikhry.orchestrator.models.command import CommandEnvelope
from vikhry.orchestrator.models.test_state import TestState
from vikhry.orchestrator.models.user import UserAssignment, UserRuntimeStatus
from vikhry.orchestrator.models.worker import WorkerStatus

_CAS_STATE_SCRIPT = """
local current = redis.call("GET", KEYS[1])
if not current then
  current = ARGV[1]
  redis.call("SET", KEYS[1], ARGV[1])
end
if current ~= ARGV[1] then
  return 0
end
redis.call("SET", KEYS[1], ARGV[2])
return 1
"""

_START_PREPARING_WITH_EPOCH_SCRIPT = """
local current = redis.call("GET", KEYS[1])
if not current then
  current = ARGV[1]
  redis.call("SET", KEYS[1], ARGV[1])
end
if current ~= ARGV[1] then
  return nil
end
redis.call("SET", KEYS[1], ARGV[2])
local epoch = redis.call("INCR", KEYS[2])
return epoch
"""


class TestStateRepository:
    def __init__(self, redis_client: Redis) -> None:
        self._redis = redis_client

    @staticmethod
    def worker_status_key(worker_id: str) -> str:
        return f"worker:{worker_id}:status"

    @staticmethod
    def worker_users_key(worker_id: str) -> str:
        return f"worker:{worker_id}:users"

    @staticmethod
    def worker_active_users_key(worker_id: str) -> str:
        return f"worker:{worker_id}:active_users"

    @staticmethod
    def worker_command_channel(worker_id: str) -> str:
        return f"worker:{worker_id}:commands"

    @staticmethod
    def user_key(user_id: int | str) -> str:
        return f"user:{user_id}"

    @staticmethod
    def resource_key(resource_name: str, resource_id: int | str) -> str:
        return f"resource:{resource_name}:{resource_id}"

    @staticmethod
    def metric_stream_key(metric_id: str) -> str:
        return f"metric:{metric_id}"

    @staticmethod
    def users_timeline_stream_key() -> str:
        return "users:timeline"

    async def initialize_defaults(self) -> None:
        await self._redis.setnx("test:state", TestState.IDLE.value)
        await self._redis.setnx("test:epoch", 0)

    async def get_state(self) -> TestState:
        value = await self._redis.get("test:state")
        if not value:
            return TestState.IDLE
        return TestState(value)

    async def get_epoch(self) -> int:
        value = await self._redis.get("test:epoch")
        if value is None:
            return 0
        return int(value)

    async def set_state(self, state: TestState) -> None:
        await self._redis.set("test:state", state.value)

    async def compare_and_set_state(self, expected: TestState, new_state: TestState) -> bool:
        changed = await self._redis.eval(
            _CAS_STATE_SCRIPT, 1, "test:state", expected.value, new_state.value
        )
        return bool(changed)

    async def start_preparing_and_bump_epoch(self) -> int | None:
        epoch = await self._redis.eval(
            _START_PREPARING_WITH_EPOCH_SCRIPT,
            2,
            "test:state",
            "test:epoch",
            TestState.IDLE.value,
            TestState.PREPARING.value,
        )
        return int(epoch) if epoch is not None else None

    async def increment_epoch(self) -> int:
        return int(await self._redis.incr("test:epoch"))

    async def register_worker(self, worker_id: str) -> None:
        await self._redis.sadd("workers", worker_id)

    async def unregister_worker(self, worker_id: str) -> None:
        pipeline = self._redis.pipeline()
        pipeline.srem("workers", worker_id)
        pipeline.delete(self.worker_status_key(worker_id))
        pipeline.delete(self.worker_users_key(worker_id))
        pipeline.delete(self.worker_active_users_key(worker_id))
        await pipeline.execute()

    async def list_workers(self) -> list[str]:
        workers = await self._redis.smembers("workers")
        return sorted(str(worker_id) for worker_id in workers)

    async def set_worker_status(self, worker_id: str, status: WorkerStatus) -> None:
        await self._redis.hset(
            self.worker_status_key(worker_id),
            mapping={
                "status": status.status.value,
                "last_heartbeat": str(status.last_heartbeat),
            },
        )

    async def get_worker_status(self, worker_id: str) -> WorkerStatus | None:
        raw_status = await self._redis.hgetall(self.worker_status_key(worker_id))
        if not raw_status:
            return None
        return WorkerStatus.model_validate(raw_status)

    async def add_worker_user(self, worker_id: str, user_id: int | str) -> None:
        await self._redis.sadd(self.worker_users_key(worker_id), str(user_id))

    async def remove_worker_user(self, worker_id: str, user_id: int | str) -> None:
        await self._redis.srem(self.worker_users_key(worker_id), str(user_id))

    async def list_worker_users(self, worker_id: str) -> list[str]:
        users = await self._redis.smembers(self.worker_users_key(worker_id))
        return sorted(str(user_id) for user_id in users)

    async def count_worker_active_users(self, worker_id: str) -> int:
        return int(await self._redis.scard(self.worker_active_users_key(worker_id)))

    async def add_user_assignment(self, assignment: UserAssignment) -> None:
        user_id = str(assignment.user_id)
        pipeline = self._redis.pipeline()
        pipeline.sadd("users", user_id)
        pipeline.hset(
            self.user_key(user_id),
            mapping={
                "status": assignment.status.value,
                "worker_id": assignment.worker_id,
                "updated_at": str(assignment.updated_at),
            },
        )
        pipeline.sadd(self.worker_users_key(assignment.worker_id), user_id)
        await pipeline.execute()

    async def get_user_assignment(self, user_id: int | str) -> UserAssignment | None:
        raw = await self._redis.hgetall(self.user_key(user_id))
        if not raw:
            return None
        return UserAssignment.model_validate({"user_id": str(user_id), **raw})

    async def remove_user_assignment(self, user_id: int | str) -> None:
        user_key = self.user_key(user_id)
        worker_id = await self._redis.hget(user_key, "worker_id")
        pipeline = self._redis.pipeline()
        pipeline.srem("users", str(user_id))
        pipeline.delete(user_key)
        if worker_id:
            pipeline.srem(self.worker_users_key(str(worker_id)), str(user_id))
        await pipeline.execute()

    async def list_users(self) -> list[str]:
        users = await self._redis.smembers("users")
        return sorted(str(user_id) for user_id in users)

    async def clear_users_data(self) -> None:
        users = await self.list_users()
        workers = await self.list_workers()
        pipeline = self._redis.pipeline()
        pipeline.delete("users")
        for user_id in users:
            pipeline.delete(self.user_key(user_id))
        for worker_id in workers:
            pipeline.delete(self.worker_users_key(worker_id))
            pipeline.delete(self.worker_active_users_key(worker_id))
        await pipeline.execute()

    async def set_user_status(
        self, user_id: int | str, status: UserRuntimeStatus, updated_at: int
    ) -> bool:
        key = self.user_key(user_id)
        exists = await self._redis.exists(key)
        if not exists:
            return False
        await self._redis.hset(
            key,
            mapping={"status": status.value, "updated_at": str(updated_at)},
        )
        return True

    async def set_all_users_status(self, status: UserRuntimeStatus, updated_at: int) -> int:
        users = await self.list_users()
        if not users:
            return 0
        pipeline = self._redis.pipeline()
        for user_id in users:
            pipeline.hset(
                self.user_key(user_id),
                mapping={"status": status.value, "updated_at": str(updated_at)},
            )
        await pipeline.execute()
        return len(users)

    async def increment_resource_counter(self, resource_name: str, delta: int = 1) -> int:
        return int(await self._redis.hincrby("resources", resource_name, delta))

    async def list_resource_counters(self) -> dict[str, int]:
        raw = await self._redis.hgetall("resources")
        return {name: int(count) for name, count in raw.items()}

    async def set_resource_data(
        self, resource_name: str, resource_id: int | str, payload: dict[str, Any]
    ) -> None:
        await self._redis.set(
            self.resource_key(resource_name, resource_id),
            orjson.dumps(payload),
        )

    async def get_resource_data(
        self, resource_name: str, resource_id: int | str
    ) -> dict[str, Any] | None:
        raw = await self._redis.get(self.resource_key(resource_name, resource_id))
        if raw is None:
            return None
        parsed = orjson.loads(raw)
        if not isinstance(parsed, dict):
            raise TypeError("Resource payload must be JSON object")
        return parsed

    async def register_metric(self, metric_id: str) -> None:
        await self._redis.sadd("metrics", metric_id)

    async def list_metrics(self) -> list[str]:
        metrics = await self._redis.smembers("metrics")
        return sorted(str(metric) for metric in metrics)

    async def clear_metrics_data(self) -> int:
        keys_to_delete: list[str] = ["metrics"]
        cursor = 0
        while True:
            cursor, keys = await self._redis.scan(
                cursor=cursor,
                match="metric:*",
                count=500,
            )
            if keys:
                keys_to_delete.extend(str(key) for key in keys)
            if cursor == 0:
                break
        if not keys_to_delete:
            return 0
        return int(await self._redis.delete(*keys_to_delete))

    async def clear_users_timeline(self) -> int:
        return int(await self._redis.delete(self.users_timeline_stream_key()))

    async def append_metric_event(self, metric_id: str, event: dict[str, Any]) -> str:
        await self.register_metric(metric_id)
        event_id = await self._redis.xadd(
            self.metric_stream_key(metric_id),
            {"data": orjson.dumps(event).decode("utf-8")},
        )
        return str(event_id)

    async def append_users_timeline_event(
        self,
        *,
        epoch: int,
        users_count: int,
        source: str,
    ) -> str:
        event_id = await self._redis.xadd(
            self.users_timeline_stream_key(),
            {
                "epoch": str(epoch),
                "users_count": str(max(0, users_count)),
                "source": source,
            },
        )
        return str(event_id)

    async def read_metric_events(
        self,
        metric_id: str,
        start: str = "-",
        end: str = "+",
        count: int = 100,
    ) -> list[dict[str, Any]]:
        items = await self._redis.xrange(
            self.metric_stream_key(metric_id),
            min=start,
            max=end,
            count=count,
        )
        parsed_items: list[dict[str, Any]] = []
        for event_id, values in items:
            raw_payload = values.get("data")
            payload = (
                orjson.loads(raw_payload)
                if raw_payload is not None
                else {}
            )
            parsed_items.append({"event_id": str(event_id), "data": payload})
        return parsed_items

    async def read_metric_events_after(
        self,
        metric_id: str,
        after_event_id: str | None,
        count: int = 100,
    ) -> list[dict[str, Any]]:
        if after_event_id is None:
            return await self.read_metric_events(metric_id=metric_id, count=count)
        items = await self.read_metric_events(
            metric_id=metric_id,
            start=after_event_id,
            end="+",
            count=count + 1,
        )
        filtered = [item for item in items if item["event_id"] != after_event_id]
        return filtered[:count]

    async def read_users_timeline_events(
        self,
        start: str = "-",
        end: str = "+",
        count: int = 100,
    ) -> list[dict[str, Any]]:
        items = await self._redis.xrange(
            self.users_timeline_stream_key(),
            min=start,
            max=end,
            count=count,
        )
        parsed_items: list[dict[str, Any]] = []
        for event_id, values in items:
            raw_epoch = values.get("epoch")
            raw_users_count = values.get("users_count")
            raw_source = values.get("source")
            try:
                epoch = int(raw_epoch) if raw_epoch is not None else 0
            except (TypeError, ValueError):
                epoch = 0
            try:
                users_count = int(raw_users_count) if raw_users_count is not None else 0
            except (TypeError, ValueError):
                users_count = 0
            parsed_items.append(
                {
                    "event_id": str(event_id),
                    "epoch": epoch,
                    "users_count": max(0, users_count),
                    "source": str(raw_source) if raw_source is not None else "unknown",
                }
            )
        return parsed_items

    async def read_users_timeline_events_after(
        self,
        after_event_id: str | None,
        count: int = 100,
    ) -> list[dict[str, Any]]:
        if after_event_id is None:
            return await self.read_users_timeline_events(count=count)
        items = await self.read_users_timeline_events(
            start=after_event_id,
            end="+",
            count=count + 1,
        )
        filtered = [item for item in items if item["event_id"] != after_event_id]
        return filtered[:count]

    async def publish_worker_command(self, worker_id: str, command: CommandEnvelope) -> int:
        return int(
            await self._redis.publish(
                self.worker_command_channel(worker_id),
                command.to_json_bytes(),
            )
        )

    @staticmethod
    def decode_command(raw: bytes | bytearray | memoryview | str) -> CommandEnvelope:
        return CommandEnvelope.from_json_bytes(raw)
