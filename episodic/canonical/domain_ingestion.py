"""Ingestion job and source-document domain models."""

import dataclasses as dc
import typing as typ

from .domain_enums import IngestionStatus, IntakeState

if typ.TYPE_CHECKING:
    import datetime as dt
    import uuid

    from .domain_enums import JsonMapping


@dc.dataclass(frozen=True, slots=True)
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
    owner_principal_id: str | None = None


@dc.dataclass(frozen=True, slots=True)
class IngestionJobListFilters:
    """Filters for listing source-intake ingestion jobs."""

    series_profile_id: uuid.UUID | None
    intake_state: IntakeState | None
    owner_principal_id: str | None = None


@dc.dataclass(frozen=True, slots=True)
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
class SourceDocumentInput:
    """Input payload for new source documents."""

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
