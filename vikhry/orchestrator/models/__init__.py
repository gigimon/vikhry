"""Domain models for orchestrator."""

from vikhry.orchestrator.models.api import ChangeUsersRequest, StartTestRequest
from vikhry.orchestrator.models.command import (
    AddUserPayload,
    CommandEnvelope,
    CommandType,
    RemoveUserPayload,
    StartTestPayload,
    StopTestPayload,
)
from vikhry.orchestrator.models.resource import CreateResourceRequest, CreateResourceResult
from vikhry.orchestrator.models.settings import OrchestratorSettings
from vikhry.orchestrator.models.test_state import TestState
from vikhry.orchestrator.models.user import UserAssignment, UserRuntimeStatus
from vikhry.orchestrator.models.worker import WorkerHealthStatus, WorkerStatus

__all__ = [
    "AddUserPayload",
    "ChangeUsersRequest",
    "CommandEnvelope",
    "CommandType",
    "CreateResourceRequest",
    "CreateResourceResult",
    "OrchestratorSettings",
    "RemoveUserPayload",
    "StartTestPayload",
    "StartTestRequest",
    "StopTestPayload",
    "TestState",
    "UserAssignment",
    "UserRuntimeStatus",
    "WorkerHealthStatus",
    "WorkerStatus",
]
