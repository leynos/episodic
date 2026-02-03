"""Domain models for canonical content storage."""

from __future__ import annotations

import dataclasses as dc
import enum
import typing as typ

if typ.TYPE_CHECKING:
    import datetime as dt
    import uuid

type JsonMapping = dict[str, typ.Any]


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
