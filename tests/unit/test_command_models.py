from __future__ import annotations

import pytest
from pydantic import ValidationError

from vikhry.orchestrator.models.command import (
    AddUserPayload,
    CommandEnvelope,
    CommandType,
    StartTestPayload,
)


def test_command_envelope_roundtrip_spec() -> None:
    command = CommandEnvelope(
        type=CommandType.ADD_USER,
        command_id="cmd-1",
        epoch=2,
        sent_at=1_761_571_200,
        payload={"user_id": 42},
    )

    raw = command.to_json_bytes()
    restored = CommandEnvelope.from_json_bytes(raw)

    payload = restored.require_payload(AddUserPayload)
    assert payload.user_id == 42
    assert restored.command_id == "cmd-1"
    assert restored.epoch == 2


def test_command_envelope_rejects_mismatched_payload_spec() -> None:
    with pytest.raises(ValidationError):
        CommandEnvelope(
            type=CommandType.START_TEST,
            command_id="cmd-2",
            epoch=1,
            sent_at=1_761_571_200,
            payload={"user_id": 7},
        )


def test_require_payload_type_guard_spec() -> None:
    command = CommandEnvelope(
        type=CommandType.START_TEST,
        command_id="cmd-3",
        epoch=1,
        sent_at=1_761_571_200,
        payload=StartTestPayload(target_users=10),
    )

    with pytest.raises(TypeError):
        command.require_payload(AddUserPayload)


def test_start_test_payload_accepts_init_params_spec() -> None:
    command = CommandEnvelope(
        type=CommandType.START_TEST,
        command_id="cmd-4",
        epoch=1,
        sent_at=1_761_571_200,
        payload={"target_users": 2, "init_params": {"tenant": "acme", "warmup": 3}},
    )

    payload = command.require_payload(StartTestPayload)
    assert payload.init_params == {"tenant": "acme", "warmup": 3}
