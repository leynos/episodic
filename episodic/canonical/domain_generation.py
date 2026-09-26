"""User-facing generation run and checkpoint domain models."""

import dataclasses as dc
import datetime as dt
import typing as typ

from .domain_enums import CheckpointAction, CheckpointStatus, GenerationRunStatus
from .domain_validation import (
    _copy_json_mapping,
    _is_blank,
    _validate_draft_without_qa_metadata,
    _validate_non_empty_text,
    _validate_optional_text,
)
from .generation_quality import QaStatus, QualityMode
from .generation_run_errors import CheckpointAlreadyTerminal

if typ.TYPE_CHECKING:
    import uuid

    from .domain_enums import JsonMapping


def _require_lifecycle_field_types(
    *,
    current_node: object,
    ended_at: object,
) -> None:
    """Reject a mistyped lifecycle field before any value check runs.

    The parameters are deliberately the unnarrowed types: this function's
    whole job is to establish those types at runtime. It is separate from
    :func:`_validate_terminal_run_lifecycle` so the ordering rule -- a
    mistyped field reports its type and never the lifecycle rule, even on a
    terminal run -- is expressed by the call order rather than by reading
    down a single function.

    Raises
    ------
    TypeError
        If ``current_node`` is neither ``None`` nor a string, or ``ended_at``
        is neither ``None`` nor a :class:`datetime.datetime`.
    """
    if current_node is not None and not isinstance(current_node, str):
        msg = "current_node must be a string."
        raise TypeError(msg)
    if ended_at is not None and not isinstance(ended_at, dt.datetime):
        msg = "ended_at must be a datetime."
        raise TypeError(msg)


def _validate_terminal_run_lifecycle(
    *,
    status: GenerationRunStatus,
    current_node: str | None,
    ended_at: dt.datetime | None,
) -> None:
    """Validate lifecycle fields required by terminal generation runs."""
    _require_lifecycle_field_types(current_node=current_node, ended_at=ended_at)
    if not status.is_terminal():
        return
    if current_node is not None:
        msg = "terminal generation runs must not have a current node"
        raise ValueError(msg)
    if ended_at is None:
        msg = "terminal generation runs must have an end time"
        raise ValueError(msg)


@dc.dataclass(frozen=True, slots=True)
class GenerationRun:
    """User-facing generation run aggregate root."""

    id: uuid.UUID
    episode_id: uuid.UUID
    source_bundle_id: uuid.UUID
    actor: str
    status: GenerationRunStatus
    current_node: str | None
    budget_snapshot: JsonMapping
    configuration: JsonMapping
    created_at: dt.datetime
    updated_at: dt.datetime
    started_at: dt.datetime | None
    ended_at: dt.datetime | None
    error_message: str | None
    error_category: str | None = None
    quality_mode: QualityMode = QualityMode.DRAFT_WITHOUT_QA
    qa_status: QaStatus | None = None
    skip_qa_rationale: str | None = None

    def __post_init__(self) -> None:
        """Validate generation-run invariants."""
        _validate_terminal_run_lifecycle(
            status=self.status,
            current_node=self.current_node,
            ended_at=self.ended_at,
        )
        _validate_non_empty_text(self.actor, "actor")
        _validate_optional_text(self.current_node, "current_node")
        _validate_optional_text(self.error_message, "error_message")
        _validate_optional_text(self.error_category, "error_category")
        _validate_draft_without_qa_metadata(
            quality_mode=self.quality_mode,
            qa_status=self.qa_status,
            skip_qa_rationale=self.skip_qa_rationale,
        )
        _copy_json_mapping(self, "budget_snapshot")
        _copy_json_mapping(self, "configuration")


@dc.dataclass(frozen=True, slots=True)
class GenerationEvent:
    """Append-only event emitted by a generation run."""

    id: uuid.UUID
    generation_run_id: uuid.UUID
    seq: int
    kind: str
    payload: JsonMapping
    created_at: dt.datetime
    occurred_at: dt.datetime

    def __post_init__(self) -> None:
        """Validate event identity and payload invariants."""
        if not isinstance(self.seq, int) or self.seq < 1:
            msg = "seq must be a positive integer."
            raise ValueError(msg)
        _validate_non_empty_text(self.kind, "kind")
        _copy_json_mapping(self, "payload")


@dc.dataclass(frozen=True, slots=True)
class CheckpointResponse:
    """Value-object capturing a reviewer's response to a checkpoint."""

    action: CheckpointAction
    payload: JsonMapping
    responded_at: dt.datetime
    responded_by: str

    def __post_init__(self) -> None:
        """Validate response invariants."""
        _validate_non_empty_text(self.responded_by, "responded_by")
        _copy_json_mapping(self, "payload")


@dc.dataclass(frozen=True, slots=True)
class Checkpoint:
    """Human review checkpoint attached to a generation run."""

    id: uuid.UUID
    generation_run_id: uuid.UUID
    node: str
    prompt: str
    options: tuple[str, ...]
    status: CheckpointStatus
    created_at: dt.datetime
    responded_at: dt.datetime | None
    responded_by: str | None
    response_action: CheckpointAction | None
    response_payload: JsonMapping

    def __post_init__(self) -> None:
        """Validate checkpoint lifecycle invariants."""
        _validate_non_empty_text(self.node, "node")
        _validate_non_empty_text(self.prompt, "prompt")
        self._validate_options()
        _validate_optional_text(self.responded_by, "responded_by")
        _copy_json_mapping(self, "response_payload")
        self._validate_responded_fields()

    def _validate_options(self) -> None:
        """Validate that checkpoint options are present and selectable."""
        if len(self.options) == 0:
            msg = "options must contain at least one action."
            raise ValueError(msg)
        if any(
            not isinstance(option, str) or _is_blank(option) for option in self.options
        ):
            msg = "options must contain non-empty strings."
            raise ValueError(msg)

    def _validate_responded_fields(self) -> None:
        """Validate required fields for responded checkpoints."""
        if self.status is not CheckpointStatus.RESPONDED:
            return
        if self.responded_at is None:
            msg = "responded checkpoints require responded_at."
            raise ValueError(msg)
        if self.responded_by is None:
            msg = "responded checkpoints require responded_by."
            raise ValueError(msg)
        if self.response_action is None:
            msg = "responded checkpoints require response_action."
            raise ValueError(msg)

    def respond(self, response: CheckpointResponse) -> Checkpoint:
        """Return a responded checkpoint."""
        self._raise_if_terminal()
        return dc.replace(
            self,
            status=CheckpointStatus.RESPONDED,
            responded_at=response.responded_at,
            responded_by=response.responded_by,
            response_action=response.action,
            response_payload=response.payload,
        )

    def time_out(self, at: dt.datetime) -> Checkpoint:
        """Return a timed-out checkpoint."""
        self._raise_if_terminal()
        return dc.replace(
            self,
            status=CheckpointStatus.TIMED_OUT,
            responded_at=at,
        )

    def cancel(self, at: dt.datetime) -> Checkpoint:
        """Return a cancelled checkpoint."""
        self._raise_if_terminal()
        return dc.replace(
            self,
            status=CheckpointStatus.CANCELLED,
            responded_at=at,
        )

    def _raise_if_terminal(self) -> None:
        """Raise when the checkpoint can no longer transition."""
        if self.status.is_terminal():
            raise CheckpointAlreadyTerminal(self.id)
