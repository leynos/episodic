"""Domain models for canonical content storage."""

import dataclasses as dc
import enum
import typing as typ

from .domain_validation import copy_json_mapping
from .generation_quality import QaStatus, QualityMode
from .generation_run_errors import CheckpointAlreadyTerminal

if typ.TYPE_CHECKING:
    import datetime as dt
    import uuid

    from .domain_records import (
        ApprovalEvent,
        CanonicalEpisode,
        EpisodeTeiUpdate,
        EpisodeTemplate,
        EpisodeTemplateHistoryEntry,
        IngestionJob,
        IngestionJobListFilters,
        IngestionRequest,
        ReferenceBinding,
        ReferenceDocument,
        ReferenceDocumentRevision,
        SeriesProfile,
        SeriesProfileHistoryEntry,
        SourceDocument,
        SourceDocumentInput,
        TeiHeader,
    )

    __all__ = (
        "ApprovalEvent",
        "CanonicalEpisode",
        "EpisodeTeiUpdate",
        "EpisodeTemplate",
        "EpisodeTemplateHistoryEntry",
        "IngestionJob",
        "IngestionJobListFilters",
        "IngestionRequest",
        "ReferenceBinding",
        "ReferenceDocument",
        "ReferenceDocumentRevision",
        "SeriesProfile",
        "SeriesProfileHistoryEntry",
        "SourceDocument",
        "SourceDocumentInput",
        "TeiHeader",
    )

type JsonMapping = dict[str, object]


class EpisodeStatus(enum.StrEnum):
    """Lifecycle states for canonical episodes."""

    DRAFT = "draft"
    IN_PROGRESS = "in_progress"
    QUALITY_REVIEW = "quality_review"
    EDITORIAL_REVIEW = "editorial_review"
    ON_HOLD = "on_hold"
    REJECTED = "rejected"
    AUDIO_GENERATION = "audio_generation"
    POST_PROCESSING = "post_processing"
    READY_TO_PUBLISH = "ready_to_publish"
    SCHEDULED = "scheduled"
    PUBLISHED = "published"
    UPDATED = "updated"
    FAILED = "failed"
    ARCHIVED = "archived"


class ApprovalState(enum.StrEnum):
    """Approval workflow states for canonical episodes."""

    DRAFT = "draft"
    SUBMITTED = "submitted"
    APPROVED = "approved"
    REJECTED = "rejected"


class IngestionStatus(enum.StrEnum):
    """Status values for ingestion jobs."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class IntakeState(enum.StrEnum):
    """Source-intake states for pre-generation ingestion jobs."""

    AWAITING_SOURCES = "awaiting_sources"
    READY_FOR_GENERATION = "ready_for_generation"
    CANCELLED = "cancelled"


class ReferenceDocumentKind(enum.StrEnum):
    """Supported reusable reference-document kinds."""

    STYLE_GUIDE = "style_guide"
    HOST_PROFILE = "host_profile"
    GUEST_PROFILE = "guest_profile"
    RESEARCH_BRIEF = "research_brief"


class ReferenceDocumentLifecycleState(enum.StrEnum):
    """Lifecycle states for reusable reference documents."""

    DRAFT = "draft"
    ACTIVE = "active"
    ARCHIVED = "archived"


class ReferenceBindingTargetKind(enum.StrEnum):
    """Supported target contexts for reusable reference bindings."""

    SERIES_PROFILE = "series_profile"
    EPISODE_TEMPLATE = "episode_template"
    INGESTION_JOB = "ingestion_job"


class WorkflowCheckpointStatus(enum.StrEnum):
    """Lifecycle states for resumable orchestration checkpoints."""

    SUSPENDED = "suspended"
    RESUMED = "resumed"


class GenerationRunStatus(enum.StrEnum):
    """Lifecycle states for user-facing generation runs."""

    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"

    def is_terminal(self) -> bool:
        """Return whether this status is a terminal run state."""
        return self in {
            GenerationRunStatus.SUCCEEDED,
            GenerationRunStatus.FAILED,
            GenerationRunStatus.CANCELLED,
        }


class CheckpointStatus(enum.StrEnum):
    """Lifecycle states for user-facing generation checkpoints."""

    CREATED = "created"
    RESPONDED = "responded"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"

    def is_terminal(self) -> bool:
        """Return whether this status is a terminal checkpoint state."""
        return self is not CheckpointStatus.CREATED


class CheckpointAction(enum.StrEnum):
    """Reviewer actions accepted for a generation checkpoint."""

    APPROVE = "approve"
    REQUEST_CHANGES = "request_changes"
    EDIT = "edit"


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
        _validate_non_empty_text(self.actor, "actor")
        _validate_optional_text(self.current_node, "current_node")
        _validate_optional_text(self.error_message, "error_message")
        _validate_optional_text(self.error_category, "error_category")
        _validate_draft_without_qa_metadata(
            quality_mode=self.quality_mode,
            qa_status=self.qa_status,
            skip_qa_rationale=self.skip_qa_rationale,
        )
        copy_json_mapping(self, "budget_snapshot")
        copy_json_mapping(self, "configuration")


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
        copy_json_mapping(self, "payload")


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
        copy_json_mapping(self, "payload")


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
        copy_json_mapping(self, "response_payload")
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


def _is_blank(value: str) -> bool:
    """Return whether a string is empty after whitespace trimming."""
    return not value.strip()


def _validate_non_empty_text(value: str, field_name: str) -> None:
    """Validate a required non-empty string field."""
    if not isinstance(value, str):
        msg = f"{field_name} must be a string."
        raise TypeError(msg)
    if _is_blank(value):
        msg = f"{field_name} must be a non-empty string."
        raise ValueError(msg)


def _validate_optional_text(value: str | None, field_name: str) -> None:
    """Validate an optional string field when present."""
    if value is not None:
        _validate_non_empty_text(value, field_name)


def _validate_draft_without_qa_metadata(
    *,
    quality_mode: QualityMode,
    qa_status: QaStatus | None,
    skip_qa_rationale: str | None,
) -> None:
    """Validate the no-QA slice's required audit metadata."""
    if quality_mode is not QualityMode.DRAFT_WITHOUT_QA:
        msg = f"Unsupported quality_mode: {quality_mode!s}."
        raise ValueError(msg)
    if qa_status is not QaStatus.SKIPPED:
        msg = "qa_status must be skipped for draft_without_qa runs."
        raise ValueError(msg)
    if skip_qa_rationale is None:
        msg = "skip_qa_rationale must be a non-empty string."
        raise ValueError(msg)
    _validate_non_empty_text(skip_qa_rationale, "skip_qa_rationale")


_RECORD_NAMES = frozenset({
    "ApprovalEvent",
    "CanonicalEpisode",
    "EpisodeTeiUpdate",
    "EpisodeTemplate",
    "EpisodeTemplateHistoryEntry",
    "IngestionJob",
    "IngestionJobListFilters",
    "IngestionRequest",
    "ReferenceBinding",
    "ReferenceDocument",
    "ReferenceDocumentRevision",
    "SeriesProfile",
    "SeriesProfileHistoryEntry",
    "SourceDocument",
    "SourceDocumentInput",
    "TeiHeader",
})


def __getattr__(name: str) -> object:
    """Lazily resolve record types to keep domain model boundaries acyclic."""
    if name not in _RECORD_NAMES:
        raise AttributeError(name)
    from episodic.canonical import domain_records

    return getattr(domain_records, name)
