"""Checkpoint DTOs for resumable generation orchestration."""

import dataclasses as dc
import datetime as dt  # noqa: TC003 - runtime annotation inspection needs this name.
import json

from ._payload_dto import (
    ActionExecutionResult,
    _normalize_non_empty_text,
    _normalize_string_fields,
)


@dc.dataclass(frozen=True, slots=True)
class WorkflowCheckpoint:
    """Durable orchestration state saved when a generation workflow pauses.

    `CheckpointPort` implementations persist this DTO before the graph crosses
    an external boundary. `workflow_id`, `workflow_type`, `step_name`, and
    `idempotency_key` identify the resumable step; `payload` stores the
    JSON-shaped graph state needed by `resume_generation_orchestration`.
    """

    checkpoint_id: str
    workflow_id: str
    workflow_type: str
    step_name: str
    idempotency_key: str
    payload: dict[str, object]
    status: str = "suspended"
    created_at: dt.datetime | None = None
    updated_at: dt.datetime | None = None

    def __post_init__(self) -> None:
        """Validate checkpoint identity fields and freeze the payload mapping."""
        _normalize_string_fields(
            self,
            (
                "checkpoint_id",
                "workflow_id",
                "workflow_type",
                "step_name",
                "idempotency_key",
                "status",
            ),
        )
        if not isinstance(self.payload, dict):
            msg = "payload must be a mapping object."
            raise TypeError(msg)
        try:
            json.dumps(self.payload, allow_nan=False)
        except (TypeError, ValueError) as exc:
            msg = "payload must be JSON-serializable."
            raise TypeError(msg) from exc
        object.__setattr__(self, "payload", dict(self.payload))


@dc.dataclass(frozen=True, slots=True)
class SuspendedWorkflowResult:
    """Typed result returned when a graph pauses before external work resumes it.

    API handlers and worker dispatchers can use this value to expose the
    checkpoint identifier and idempotency key without depending on LangGraph
    state internals or storage adapter records.
    """

    checkpoint_id: str
    workflow_id: str
    step_name: str
    idempotency_key: str

    def __post_init__(self) -> None:
        """Reject blank suspend metadata."""
        _normalize_string_fields(
            self,
            ("checkpoint_id", "workflow_id", "step_name", "idempotency_key"),
        )


@dc.dataclass(frozen=True, slots=True)
class ResumeWorkflowCommand:
    """Input for resuming a suspended workflow from a durable checkpoint.

    The command combines the checkpoint identifier with the externally produced
    action result. `TaskResumePort` implementations validate or transform that
    result before the graph aggregates the final orchestration outcome.
    """

    checkpoint_id: str
    result: ActionExecutionResult

    def __post_init__(self) -> None:
        """Validate resume identity and result shape."""
        object.__setattr__(
            self,
            "checkpoint_id",
            _normalize_non_empty_text(self.checkpoint_id, "checkpoint_id"),
        )
        if not isinstance(self.result, ActionExecutionResult):
            msg = "result must be an ActionExecutionResult."
            raise TypeError(msg)


@dc.dataclass(frozen=True, slots=True)
class WorkflowStepIdentity:
    """Stable identity fields for one resumable workflow step."""

    workflow_id: str
    workflow_type: str
    step_name: str
    action_id: str

    def __post_init__(self) -> None:
        """Normalise identity fields eagerly."""
        for field_name in ("workflow_id", "workflow_type", "step_name", "action_id"):
            object.__setattr__(
                self,
                field_name,
                _normalize_non_empty_text(getattr(self, field_name), field_name),
            )


def build_workflow_step_idempotency_key(
    step: WorkflowStepIdentity,
    *,
    attempt: int = 0,
) -> str:
    """Build the deterministic idempotency key for a suspendable workflow step."""
    if attempt < 0:
        msg = "attempt must be greater than or equal to zero."
        raise ValueError(msg)
    parts = (
        step.workflow_id,
        step.workflow_type,
        step.step_name,
        step.action_id,
        str(attempt),
    )
    return ":".join(parts)
