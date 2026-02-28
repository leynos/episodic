"""Domain models for canonical content storage."""

import dataclasses as dc
import enum
import typing as typ

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


@dc.dataclass(frozen=True)
class SeriesProfile:
    """Series metadata required for canonical ingestion."""

    id: uuid.UUID
    slug: str
    title: str
    description: str | None
    configuration: JsonMapping
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


@dc.dataclass(frozen=True)
class SourceDocument:
    """Source document metadata for ingestion jobs."""

    id: uuid.UUID
    ingestion_job_id: uuid.UUID
    canonical_episode_id: uuid.UUID | None
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

        populated_target = populated_targets[0]
        if populated_target is not self.target_kind:
            msg = "ReferenceBinding target_kind does not match populated target."
            raise ValueError(msg)

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


@dc.dataclass(frozen=True)
class IngestionRequest:
    """Input payload for canonical ingestion."""

    tei_xml: str
    sources: list[SourceDocumentInput]
    requested_by: str | None


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
