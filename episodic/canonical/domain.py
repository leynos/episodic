"""Domain models for canonical content storage."""

import dataclasses as dc
import enum
import typing as typ

from .generation_run_errors import CheckpointAlreadyTerminal

if typ.TYPE_CHECKING:
    import datetime as dt
    import uuid

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

    def __post_init__(self) -> None:
        """Validate generation-run invariants."""
        _validate_non_empty_text(self.actor, "actor")
        _validate_optional_text(self.current_node, "current_node")
        _validate_optional_text(self.error_message, "error_message")
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
        if len(self.options) == 0:
            msg = "options must contain at least one action."
            raise ValueError(msg)
        if any(
            not isinstance(option, str) or _is_blank(option) for option in self.options
        ):
            msg = "options must contain non-empty strings."
            raise ValueError(msg)
        _validate_optional_text(self.responded_by, "responded_by")
        _copy_json_mapping(self, "response_payload")
        if self.status is CheckpointStatus.RESPONDED:
            if self.responded_at is None:
                msg = "responded checkpoints require responded_at."
                raise ValueError(msg)
            if self.responded_by is None:
                msg = "responded checkpoints require responded_by."
                raise ValueError(msg)
            if self.response_action is None:
                msg = "responded checkpoints require response_action."
                raise ValueError(msg)

    def respond(
        self,
        *,
        action: CheckpointAction,
        payload: JsonMapping,
        responded_at: dt.datetime,
        responded_by: str,
    ) -> Checkpoint:
        """Return a responded checkpoint."""
        self._raise_if_terminal()
        return dc.replace(
            self,
            status=CheckpointStatus.RESPONDED,
            responded_at=responded_at,
            responded_by=responded_by,
            response_action=action,
            response_payload=payload,
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


@dc.dataclass(frozen=True)
class SeriesProfile:
    """Series metadata required for canonical ingestion."""

    id: uuid.UUID
    slug: str
    title: str
    description: str | None
    configuration: JsonMapping
    guardrails: JsonMapping
    created_at: dt.datetime
    updated_at: dt.datetime


@dc.dataclass(frozen=True)
class TeiHeader:
    """Parsed TEI header payload."""

    id: uuid.UUID
    title: str
    payload: JsonMapping
    raw_xml: str
    created_at: dt.datetime
    updated_at: dt.datetime


@dc.dataclass(frozen=True)
class CanonicalEpisode:
    """Canonical episode representation."""

    id: uuid.UUID
    series_profile_id: uuid.UUID
    tei_header_id: uuid.UUID
    title: str
    tei_xml: str
    status: EpisodeStatus
    approval_state: ApprovalState
    created_at: dt.datetime
    updated_at: dt.datetime


@dc.dataclass(frozen=True)
class IngestionJob:
    """Ingestion job state for source document runs."""

    id: uuid.UUID
    series_profile_id: uuid.UUID
    target_episode_id: uuid.UUID | None
    status: IngestionStatus
    requested_at: dt.datetime
    started_at: dt.datetime | None
    completed_at: dt.datetime | None
    error_message: str | None
    created_at: dt.datetime
    updated_at: dt.datetime
    intake_state: IntakeState = IntakeState.AWAITING_SOURCES


@dc.dataclass(frozen=True, slots=True)
class IngestionJobListFilters:
    """Filters for listing source-intake ingestion jobs."""

    series_profile_id: uuid.UUID | None
    intake_state: IntakeState | None


@dc.dataclass(frozen=True)
class SourceDocument:
    """Source document metadata for ingestion jobs."""

    id: uuid.UUID
    ingestion_job_id: uuid.UUID
    canonical_episode_id: uuid.UUID | None
    reference_document_revision_id: uuid.UUID | None
    source_type: str
    source_uri: str
    weight: float
    content_hash: str
    metadata: JsonMapping
    created_at: dt.datetime


@dc.dataclass(frozen=True, slots=True)
class ReferenceDocument:
    """Reusable reference document metadata independent of ingestion jobs."""

    id: uuid.UUID
    owner_series_profile_id: uuid.UUID
    kind: ReferenceDocumentKind
    lifecycle_state: ReferenceDocumentLifecycleState
    metadata: JsonMapping
    created_at: dt.datetime
    updated_at: dt.datetime
    lock_version: int = 1

    def __post_init__(self) -> None:
        """Validate optimistic-lock invariants."""
        if not isinstance(self.lock_version, int) or self.lock_version < 1:
            msg = "lock_version must be a positive integer."
            raise ValueError(msg)


@dc.dataclass(frozen=True, slots=True)
class ReferenceDocumentRevision:
    """Immutable content revision for a reusable reference document."""

    id: uuid.UUID
    reference_document_id: uuid.UUID
    content: JsonMapping
    content_hash: str
    author: str | None
    change_note: str | None
    created_at: dt.datetime

    def __post_init__(self) -> None:
        """Validate content-hash invariants."""
        if self.content_hash.strip() == "":
            msg = "content_hash must be a non-empty string."
            raise ValueError(msg)


@dc.dataclass(frozen=True, slots=True)
class ReferenceBinding:
    """Pinned reusable reference revision linked to one target context."""

    id: uuid.UUID
    reference_document_revision_id: uuid.UUID
    target_kind: ReferenceBindingTargetKind
    series_profile_id: uuid.UUID | None
    episode_template_id: uuid.UUID | None
    ingestion_job_id: uuid.UUID | None
    effective_from_episode_id: uuid.UUID | None
    created_at: dt.datetime

    def __post_init__(self) -> None:
        """Validate target and applicability invariants."""
        self._validate_single_target()
        self._validate_target_kind_matches()
        self._validate_effective_from_constraint()

    def _validate_single_target(self) -> None:
        """Validate that exactly one target identifier is populated."""
        target_pairs = (
            (ReferenceBindingTargetKind.SERIES_PROFILE, self.series_profile_id),
            (
                ReferenceBindingTargetKind.EPISODE_TEMPLATE,
                self.episode_template_id,
            ),
            (ReferenceBindingTargetKind.INGESTION_JOB, self.ingestion_job_id),
        )
        populated_targets = [kind for kind, value in target_pairs if value is not None]
        if len(populated_targets) != 1:
            msg = "ReferenceBinding must set exactly one target identifier."
            raise ValueError(msg)

    def _validate_target_kind_matches(self) -> None:
        """Validate target_kind matches the populated target identifier."""
        target_mapping = {
            ReferenceBindingTargetKind.SERIES_PROFILE: self.series_profile_id,
            ReferenceBindingTargetKind.EPISODE_TEMPLATE: self.episode_template_id,
            ReferenceBindingTargetKind.INGESTION_JOB: self.ingestion_job_id,
        }
        populated_targets = [
            kind for kind, value in target_mapping.items() if value is not None
        ]
        populated_target = populated_targets[0]
        if populated_target is not self.target_kind:
            msg = "ReferenceBinding target_kind does not match populated target."
            raise ValueError(msg)

    def _validate_effective_from_constraint(self) -> None:
        """Validate effective_from applicability constraint."""
        if (
            self.effective_from_episode_id is not None
            and self.target_kind is not ReferenceBindingTargetKind.SERIES_PROFILE
        ):
            msg = (
                "ReferenceBinding effective_from_episode_id is only valid for "
                "series_profile targets."
            )
            raise ValueError(msg)


@dc.dataclass(frozen=True)
class ApprovalEvent:
    """Approval state transitions for canonical episodes."""

    id: uuid.UUID
    episode_id: uuid.UUID
    actor: str | None
    from_state: ApprovalState | None
    to_state: ApprovalState
    note: str | None
    payload: JsonMapping
    created_at: dt.datetime


@dc.dataclass(frozen=True)
class SourceDocumentInput:
    """Input payload for new source documents."""

    source_type: str
    source_uri: str
    weight: float
    content_hash: str
    metadata: JsonMapping
    reference_document_revision_id: uuid.UUID | None = None


@dc.dataclass(frozen=True)
class IngestionRequest:
    """Input payload for canonical ingestion."""

    tei_xml: str
    sources: list[SourceDocumentInput]
    requested_by: str | None
    episode_template_id: uuid.UUID | None = None


@dc.dataclass(frozen=True, slots=True)
class EpisodeTemplate:
    """Episode template metadata for structured brief generation.

    Attributes
    ----------
    id : uuid.UUID
        Primary key for the episode template.
    series_profile_id : uuid.UUID
        Foreign key to the owning series profile.
    slug : str
        Stable slug identifier unique within a profile.
    title : str
        Human-readable template title.
    description : str | None
        Optional longer template description.
    structure : JsonMapping
        JSON structure describing template sections.
    guardrails : JsonMapping
        Persisted LLM guardrail configuration for this template.
    created_at : dt.datetime
        Timestamp when the template was created.
    updated_at : dt.datetime
        Timestamp when the template was last updated.
    """

    id: uuid.UUID
    series_profile_id: uuid.UUID
    slug: str
    title: str
    description: str | None
    structure: JsonMapping
    guardrails: JsonMapping
    created_at: dt.datetime
    updated_at: dt.datetime


@dc.dataclass(frozen=True, slots=True)
class SeriesProfileHistoryEntry:
    """Immutable change-history entry for a series profile.

    Attributes
    ----------
    id : uuid.UUID
        Primary key for the history entry.
    series_profile_id : uuid.UUID
        Foreign key to the series profile.
    revision : int
        Monotonically increasing revision number.
    actor : str | None
        Optional identifier for the actor who made the change.
    note : str | None
        Optional free-form note describing the change.
    snapshot : JsonMapping
        Snapshot payload of the profile state at this revision.
    created_at : dt.datetime
        Timestamp when the history entry was created.
    """

    id: uuid.UUID
    series_profile_id: uuid.UUID
    revision: int
    actor: str | None
    note: str | None
    snapshot: JsonMapping
    created_at: dt.datetime


@dc.dataclass(frozen=True, slots=True)
class EpisodeTemplateHistoryEntry:
    """Immutable change-history entry for an episode template.

    Attributes
    ----------
    id : uuid.UUID
        Primary key for the history entry.
    episode_template_id : uuid.UUID
        Foreign key to the episode template.
    revision : int
        Monotonically increasing revision number.
    actor : str | None
        Optional identifier for the actor who made the change.
    note : str | None
        Optional free-form note describing the change.
    snapshot : JsonMapping
        Snapshot payload of the template state at this revision.
    created_at : dt.datetime
        Timestamp when the history entry was created.
    """

    id: uuid.UUID
    episode_template_id: uuid.UUID
    revision: int
    actor: str | None
    note: str | None
    snapshot: JsonMapping
    created_at: dt.datetime


def _is_blank(value: str) -> bool:
    """Return whether a string is empty after whitespace trimming."""
    return value.strip() == ""


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


def _copy_json_mapping(owner: object, field_name: str) -> None:
    """Validate and defensively copy a JSON mapping field."""
    value = getattr(owner, field_name)
    if not isinstance(value, dict):
        msg = f"{field_name} must be a JSON mapping."
        raise TypeError(msg)
    object.__setattr__(owner, field_name, dict(value))
