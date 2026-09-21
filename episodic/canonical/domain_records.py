"""Canonical content, intake, reference, and profile record value objects."""

import dataclasses as dc
import typing as typ

from episodic.canonical.domain import (
    ApprovalState,
    EpisodeStatus,
    IngestionStatus,
    IntakeState,
    JsonMapping,
    ReferenceBindingTargetKind,
    ReferenceDocumentKind,
    ReferenceDocumentLifecycleState,
)
from episodic.canonical.domain_validation import (
    require_positive_integer,
    require_value,
    validate_non_empty_text,
    validate_optional_text,
)

if typ.TYPE_CHECKING:
    import datetime as dt
    import uuid

    from episodic.canonical.generation_quality import QaStatus


@dc.dataclass(frozen=True, slots=True)
class SeriesProfile:
    """Series metadata that controls canonical episode generation."""

    id: uuid.UUID
    slug: str
    title: str
    description: str | None
    configuration: JsonMapping
    guardrails: JsonMapping
    created_at: dt.datetime
    updated_at: dt.datetime


@dc.dataclass(frozen=True, slots=True)
class TeiHeader:
    """Parsed TEI header and its original XML representation."""

    id: uuid.UUID
    title: str
    payload: JsonMapping
    raw_xml: str
    created_at: dt.datetime
    updated_at: dt.datetime


@dc.dataclass(frozen=True, slots=True)
class CanonicalEpisode:
    """Canonical episode content and its optimistic TEI revision."""

    id: uuid.UUID
    series_profile_id: uuid.UUID
    tei_header_id: uuid.UUID
    title: str
    tei_xml: str
    status: EpisodeStatus
    approval_state: ApprovalState
    created_at: dt.datetime
    updated_at: dt.datetime
    tei_revision: int = 1
    tei_content_hash: str | None = None
    qa_status: QaStatus | None = None
    last_generation_run_id: uuid.UUID | None = None

    def __post_init__(self) -> None:
        """Validate TEI revision metadata."""
        validate_non_empty_text(self.tei_xml, "tei_xml")
        require_positive_integer(self.tei_revision, "tei_revision")
        validate_optional_text(self.tei_content_hash, "tei_content_hash")


@dc.dataclass(frozen=True, slots=True)
class EpisodeTeiUpdate:
    """Optimistic TEI update request for a canonical episode."""

    tei_xml: str
    qa_status: QaStatus
    last_generation_run_id: uuid.UUID
    expected_revision: int
    updated_at: dt.datetime

    def __post_init__(self) -> None:
        """Validate optimistic TEI update invariants."""
        validate_non_empty_text(self.tei_xml, "tei_xml")
        require_value(self.qa_status, "qa_status")
        require_value(self.last_generation_run_id, "last_generation_run_id")
        require_positive_integer(self.expected_revision, "expected_revision")


@dc.dataclass(frozen=True, slots=True)
class IngestionJob:
    """Persistent source-intake job state."""

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
    owner_principal_id: str | None = None


@dc.dataclass(frozen=True, slots=True)
class IngestionJobListFilters:
    """Filters accepted when listing source-intake jobs."""

    series_profile_id: uuid.UUID | None
    intake_state: IntakeState | None
    owner_principal_id: str | None = None


@dc.dataclass(frozen=True, slots=True)
class SourceDocument:
    """Source document provenance linked to an ingestion job."""

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
    """Reusable reference-document metadata and lock version."""

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
        if not self.content_hash.strip():
            msg = "content_hash must be a non-empty string."
            raise ValueError(msg)


@dc.dataclass(frozen=True, slots=True)
class ReferenceBinding:
    """Pinned reusable revision linked to one target context."""

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
        targets = {
            ReferenceBindingTargetKind.SERIES_PROFILE: self.series_profile_id,
            ReferenceBindingTargetKind.EPISODE_TEMPLATE: self.episode_template_id,
            ReferenceBindingTargetKind.INGESTION_JOB: self.ingestion_job_id,
        }
        populated = [kind for kind, value in targets.items() if value is not None]
        if len(populated) != 1:
            msg = "ReferenceBinding must set exactly one target identifier."
            raise ValueError(msg)
        if populated[0] is not self.target_kind:
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


@dc.dataclass(frozen=True, slots=True)
class ApprovalEvent:
    """Approval-state transition for a canonical episode."""

    id: uuid.UUID
    episode_id: uuid.UUID
    actor: str | None
    from_state: ApprovalState | None
    to_state: ApprovalState
    note: str | None
    payload: JsonMapping
    created_at: dt.datetime


@dc.dataclass(frozen=True, slots=True)
class SourceDocumentInput:
    """Input payload for a source document created during ingestion."""

    source_type: str
    source_uri: str
    weight: float
    content_hash: str
    metadata: JsonMapping
    reference_document_revision_id: uuid.UUID | None = None


@dc.dataclass(frozen=True, slots=True)
class IngestionRequest:
    """Input payload for canonical ingestion."""

    tei_xml: str
    sources: list[SourceDocumentInput]
    requested_by: str | None
    episode_template_id: uuid.UUID | None = None


@dc.dataclass(frozen=True, slots=True)
class EpisodeTemplate:
    """Episode-template metadata and its structured generation guidance."""

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
    """Immutable revision snapshot for a series profile."""

    id: uuid.UUID
    series_profile_id: uuid.UUID
    revision: int
    actor: str | None
    note: str | None
    snapshot: JsonMapping
    created_at: dt.datetime


@dc.dataclass(frozen=True, slots=True)
class EpisodeTemplateHistoryEntry:
    """Immutable revision snapshot for an episode template."""

    id: uuid.UUID
    episode_template_id: uuid.UUID
    revision: int
    actor: str | None
    note: str | None
    snapshot: JsonMapping
    created_at: dt.datetime
