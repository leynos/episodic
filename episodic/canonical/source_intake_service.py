"""Application services for source-intake REST workflows."""

from __future__ import annotations

import asyncio
import dataclasses as dc
import datetime as dt
import hashlib
import typing as typ
import uuid

from .domain import IngestionJob, IngestionJobListFilters, IngestionStatus, IntakeState
from .ingestion_sources import AttachmentKind, IngestionJobSource
from .uploads import Upload, UploadState

if typ.TYPE_CHECKING:
    import collections.abc as cabc

    from .domain import JsonMapping
    from .object_store import ObjectStorePort
    from .pagination import Pagination
    from .unit_of_work_protocols import CanonicalUnitOfWork

    UowFactory = cabc.Callable[[], CanonicalUnitOfWork]


_UPLOAD_STORAGE_PREFIX = "uploads"


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


class SourceIntakeError(Exception):
    """Base class for source-intake domain errors."""


class SeriesProfileNotFoundError(SourceIntakeError):
    """Raised when creating a job for an unknown series profile."""


class IngestionJobNotFoundError(SourceIntakeError):
    """Raised when an ingestion job cannot be found."""


class UploadNotFoundError(SourceIntakeError):
    """Raised when a source attachment references an unknown upload."""


class UploadNotReadyError(SourceIntakeError):
    """Raised when a source attachment references a non-ready upload."""


class UploadHashMismatchError(SourceIntakeError):
    """Raised when the declared upload hash does not match stored bytes."""


class UploadSizeMismatchError(SourceIntakeError):
    """Raised when the declared upload size does not match stored bytes."""


async def register_upload(
    uow_factory: UowFactory,
    object_store: ObjectStorePort,
    request: UploadBytesRequest,
) -> Upload:
    """Persist upload bytes after committing a recoverable pending row."""
    _validate_declared_upload(request)
    upload_id = uuid.uuid4()
    storage_key = f"{_UPLOAD_STORAGE_PREFIX}/{upload_id}"
    now = dt.datetime.now(dt.UTC)
    upload = Upload(
        id=upload_id,
        owner_principal_id=request.owner_principal_id,
        content_type=request.content_type,
        declared_size=request.declared_size,
        actual_size=None,
        declared_sha256=request.declared_sha256,
        content_hash=None,
        storage_key=storage_key,
        state=UploadState.PENDING,
        metadata=request.metadata,
        created_at=now,
        updated_at=now,
    )
    async with uow_factory() as uow:
        await uow.uploads.add(upload)
        await uow.commit()
    stored = await object_store.put(
        storage_key,
        _single_chunk_stream(request.payload),
        max_bytes=request.max_bytes,
    )
    async with uow_factory() as uow:
        ready_upload = await uow.uploads.mark_ready(
            upload_id,
            content_hash=f"sha256:{stored.sha256}",
            actual_size=stored.size,
        )
        await uow.commit()
    return ready_upload


async def create_ingestion_job(
    uow: CanonicalUnitOfWork,
    request: CreateIngestionJobRequest,
) -> IngestionJob:
    """Create an intake-stage ingestion job for a known series profile."""
    profile = await uow.series_profiles.get(request.series_profile_id)
    if profile is None:
        raise SeriesProfileNotFoundError(str(request.series_profile_id))
    now = dt.datetime.now(dt.UTC)
    job = IngestionJob(
        id=uuid.uuid4(),
        series_profile_id=request.series_profile_id,
        target_episode_id=request.target_episode_id,
        status=IngestionStatus.PENDING,
        requested_at=now,
        started_at=None,
        completed_at=None,
        error_message=None,
        created_at=now,
        updated_at=now,
        intake_state=IntakeState.AWAITING_SOURCES,
    )
    await uow.ingestion_jobs.add(job)
    await uow.commit()
    return job


async def attach_source_to_ingestion_job(
    uow: CanonicalUnitOfWork,
    request: AttachSourceRequest,
) -> IngestionJobSource:
    """Attach one upload or remote URI source to an ingestion job."""
    job = await uow.ingestion_jobs.get(request.ingestion_job_id)
    if job is None:
        raise IngestionJobNotFoundError(str(request.ingestion_job_id))
    if request.attachment_kind is AttachmentKind.UPLOAD:
        await _require_ready_upload(uow, request.upload_id)
        source_uri = None
    else:
        source_uri = request.source_uri

    source = IngestionJobSource(
        id=uuid.uuid4(),
        ingestion_job_id=request.ingestion_job_id,
        attachment_kind=request.attachment_kind,
        upload_id=request.upload_id,
        source_uri=source_uri,
        source_type=request.source_type,
        weight=request.weight,
        metadata=request.metadata,
        created_at=dt.datetime.now(dt.UTC),
    )
    await uow.ingestion_job_sources.add(source)
    await uow.ingestion_jobs.transition_intake_state(
        request.ingestion_job_id,
        from_state=IntakeState.AWAITING_SOURCES,
        to_state=IntakeState.READY_FOR_GENERATION,
    )
    await uow.commit()
    return source


async def get_ingestion_job_status(
    uow: CanonicalUnitOfWork,
    job_id: uuid.UUID,
) -> IngestionJob:
    """Fetch one ingestion job or raise a source-intake not-found error."""
    job = await uow.ingestion_jobs.get(job_id)
    if job is None:
        raise IngestionJobNotFoundError(str(job_id))
    return job


async def list_ingestion_jobs(
    uow: CanonicalUnitOfWork,
    filters: IngestionJobListFilters,
    pagination: Pagination,
) -> IngestionJobPage:
    """List ingestion jobs with total count for REST pagination."""
    items = await uow.ingestion_jobs.list_paged(
        filters,
        limit=pagination.limit,
        offset=pagination.offset,
    )
    total = await uow.ingestion_jobs.count(filters)
    return IngestionJobPage(items=items, total=total, pagination=pagination)


async def _require_ready_upload(
    uow: CanonicalUnitOfWork,
    upload_id: uuid.UUID | None,
) -> Upload:
    """Return a ready upload or raise the correct source-intake error."""
    if upload_id is None:
        raise UploadNotFoundError(_UPLOAD_ID_MISSING)
    upload = await uow.uploads.get(upload_id)
    if upload is None:
        raise UploadNotFoundError(str(upload_id))
    if upload.state is not UploadState.READY:
        raise UploadNotReadyError(str(upload_id))
    return upload


def _validate_declared_upload(request: UploadBytesRequest) -> None:
    """Check client-declared size and hash against the supplied payload."""
    actual_size = len(request.payload)
    if actual_size != request.declared_size:
        raise UploadSizeMismatchError(str(request.declared_size))
    actual_hash = hashlib.sha256(request.payload).hexdigest()
    if request.declared_sha256 is not None and request.declared_sha256 != actual_hash:
        raise UploadHashMismatchError(request.declared_sha256)


async def _single_chunk_stream(payload: bytes) -> cabc.AsyncIterator[bytes]:
    """Yield a bytes payload through the object-store streaming port."""
    await asyncio.sleep(0)
    yield payload


_UPLOAD_ID_MISSING = "missing upload_id"
