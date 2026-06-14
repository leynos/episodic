"""Data shapes used by source-intake application services."""

from __future__ import annotations

import dataclasses as dc
import typing as typ

if typ.TYPE_CHECKING:
    import collections.abc as cabc
    import uuid

    from .domain import IngestionJob, JsonMapping
    from .ingestion_sources import AttachmentKind, IngestionJobSource
    from .pagination import Pagination


@dc.dataclass(frozen=True, slots=True)
class UploadBytesRequest:
    """Validated upload request data."""

    owner_principal_id: str | None
    content_type: str
    declared_size: int
    declared_sha256: str | None
    payload: bytes
    max_bytes: int
    metadata: JsonMapping


@dc.dataclass(frozen=True, slots=True)
class CreateIngestionJobRequest:
    """Request to create an intake-stage ingestion job."""

    series_profile_id: uuid.UUID
    target_episode_id: uuid.UUID | None


@dc.dataclass(frozen=True, slots=True)
class AttachSourceRequest:
    """Request to attach one source to an ingestion job."""

    ingestion_job_id: uuid.UUID
    attachment_kind: AttachmentKind
    upload_id: uuid.UUID | None
    source_uri: str | None
    source_type: str
    weight: float
    metadata: JsonMapping


@dc.dataclass(frozen=True, slots=True)
class IngestionJobPage:
    """Page of ingestion jobs plus total count."""

    items: cabc.Sequence[IngestionJob]
    total: int
    pagination: Pagination


@dc.dataclass(frozen=True, slots=True)
class IngestionJobSourcePage:
    """Page of ingestion-job sources plus total count."""

    items: cabc.Sequence[IngestionJobSource]
    total: int
    pagination: Pagination
