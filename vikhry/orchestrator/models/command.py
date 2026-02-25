from __future__ import annotations

from enum import StrEnum
from typing import Any, TypeVar

import orjson
from pydantic import BaseModel, ConfigDict, Field, model_validator


class CommandType(StrEnum):
    START_TEST = "start_test"
    STOP_TEST = "stop_test"
    ADD_USER = "add_user"
    REMOVE_USER = "remove_user"


class StartTestPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_users: int = Field(ge=0)


class StopTestPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AddUserPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: int | str


class RemoveUserPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: int | str


CommandPayload = StartTestPayload | StopTestPayload | AddUserPayload | RemoveUserPayload

_PAYLOAD_BY_TYPE: dict[CommandType, type[BaseModel]] = {
    CommandType.START_TEST: StartTestPayload,
    CommandType.STOP_TEST: StopTestPayload,
    CommandType.ADD_USER: AddUserPayload,
    CommandType.REMOVE_USER: RemoveUserPayload,
}

PayloadT = TypeVar("PayloadT", bound=BaseModel)


class CommandEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: CommandType
    command_id: str = Field(min_length=1)
    epoch: int = Field(ge=0)
    sent_at: int = Field(ge=0)
    payload: CommandPayload | dict[str, Any]

    @model_validator(mode="after")
    def _validate_payload(self) -> "CommandEnvelope":
        payload_cls = _PAYLOAD_BY_TYPE[self.type]
        payload_data = (
            self.payload.model_dump(mode="python")
            if isinstance(self.payload, BaseModel)
            else self.payload
        )
        self.payload = payload_cls.model_validate(payload_data)
        return self

    def require_payload(self, payload_type: type[PayloadT]) -> PayloadT:
        if not isinstance(self.payload, payload_type):
            raise TypeError(
                f"Command payload mismatch: expected {payload_type.__name__}, "
                f"got {type(self.payload).__name__}"
            )
        return self.payload

    def to_json_bytes(self) -> bytes:
        return orjson.dumps(self.model_dump(mode="json"))

    @classmethod
    def from_json_bytes(cls, raw: bytes | bytearray | memoryview | str) -> "CommandEnvelope":
        parsed = orjson.loads(raw)
        if not isinstance(parsed, dict):
            raise TypeError("Command envelope payload must be a JSON object")
        return cls.model_validate(parsed)

