"""Application services for source-intake REST workflows."""

from __future__ import annotations

import asyncio
import dataclasses as dc
import hashlib
import typing as typ

from episodic.logging import get_logger, log_info, log_warning

from .domain import IngestionJob, IngestionJobListFilters, IngestionStatus, IntakeState
from .ingestion_sources import AttachmentKind, IngestionJobSource
from .source_intake_errors import (
    IngestionJobNotFoundError,
    SeriesProfileNotFoundError,
    SourceIntakeError,
    UploadHashMismatchError,
    UploadNotFoundError,
    UploadNotReadyError,
    UploadSizeMismatchError,
)
from .source_intake_runtime import SourceIntakeRuntime, source_intake_runtime
from .source_intake_types import (
    AttachSourceRequest,
    CreateIngestionJobRequest,
    IngestionJobPage,
    IngestionJobSourcePage,
    UploadBytesRequest,
)
from .uploads import Upload, UploadState

if typ.TYPE_CHECKING:
    import collections.abc as cabc
    import uuid

    from .object_store import ObjectStorePort, StoredObject
    from .pagination import Pagination
    from .unit_of_work_protocols import CanonicalUnitOfWork

    UowFactory = cabc.Callable[[], CanonicalUnitOfWork]


_UPLOAD_STORAGE_PREFIX = "uploads"
logger = get_logger(__name__)
__all__ = ("SourceIntakeError",)


async def register_upload(
    uow_factory: UowFactory,
    object_store: ObjectStorePort,
    request: UploadBytesRequest,
    *,
    runtime: SourceIntakeRuntime | None = None,
) -> Upload:
    """Persist upload bytes after committing a recoverable pending row."""
    payload_sha256 = hashlib.sha256(request.payload).hexdigest()
    _validate_declared_upload(request, payload_sha256)
    providers = _source_intake_runtime(runtime)
    started_at = providers.monotonic_clock.monotonic_seconds()
    upload_id = providers.uuid_factory()
    storage_key = f"{_UPLOAD_STORAGE_PREFIX}/{upload_id}"
    now = providers.clock()
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
    await _commit_pending_upload(uow_factory, upload, providers)
    stored_upload = await _store_upload_bytes(
        object_store,
        _UploadStorageInput(
            ref=_UploadRef(id=upload_id, storage_key=storage_key),
            request=request,
            precomputed_sha256=payload_sha256,
        ),
        providers,
    )
    ready_upload = await _commit_ready_upload(
        uow_factory, stored_upload, started_at, providers
    )
    log_info(
        logger,
        "source_intake_upload_ready upload_id=%s storage_key=%s actual_size=%s",
        stored_upload.ref.id,
        stored_upload.ref.storage_key,
        stored_upload.stored.size,
    )
    providers.metrics.increment_counter(
        "source_intake_upload_events_total",
        labels={"event": "ready"},
    )
    providers.metrics.observe_latency_ms(
        "source_intake_upload_register_latency_ms",
        (providers.monotonic_clock.monotonic_seconds() - started_at) * 1000,
        labels={"outcome": "ready"},
    )
    return ready_upload


async def _commit_pending_upload(
    uow_factory: UowFactory,
    upload: Upload,
    providers: SourceIntakeRuntime,
) -> None:
    """Commit a recoverable pending upload row."""
    async with uow_factory() as uow:
        await uow.uploads.add(upload)
        await uow.commit()
    log_info(
        logger,
        ("source_intake_upload_pending upload_id=%s content_type=%s declared_size=%s"),
        upload.id,
        upload.content_type,
        upload.declared_size,
    )
    providers.metrics.increment_counter(
        "source_intake_upload_events_total",
        labels={"event": "pending_committed"},
    )


@dc.dataclass(frozen=True, slots=True)
class _UploadRef:
    id: uuid.UUID
    storage_key: str


@dc.dataclass(frozen=True, slots=True)
class _StoredUpload:
    ref: _UploadRef
    stored: StoredObject


@dc.dataclass(frozen=True, slots=True)
class _UploadStorageInput:
    ref: _UploadRef
    request: UploadBytesRequest
    precomputed_sha256: str


async def _store_upload_bytes(
    object_store: ObjectStorePort,
    storage_input: _UploadStorageInput,
    providers: SourceIntakeRuntime,
) -> _StoredUpload:
    """Store upload bytes through the object-store port."""
    stored = await object_store.put(
        storage_input.ref.storage_key,
        _single_chunk_stream(storage_input.request.payload),
        max_bytes=storage_input.request.max_bytes,
        precomputed_sha256=storage_input.precomputed_sha256,
    )
    log_info(
        logger,
        (
            "source_intake_upload_stored upload_id=%s storage_key=%s "
            "actual_size=%s content_hash=%s"
        ),
        storage_input.ref.id,
        storage_input.ref.storage_key,
        stored.size,
        f"sha256:{stored.sha256}",
    )
    providers.metrics.increment_counter(
        "source_intake_upload_events_total",
        labels={"event": "object_stored"},
    )
    return _StoredUpload(ref=storage_input.ref, stored=stored)


async def _commit_ready_upload(
    uow_factory: UowFactory,
    stored_upload: _StoredUpload,
    started_at: float,
    providers: SourceIntakeRuntime,
) -> Upload:
    """Mark a stored upload ready or preserve recovery signals on failure."""
    upload_id = stored_upload.ref.id
    storage_key = stored_upload.ref.storage_key
    stored = stored_upload.stored
    async with uow_factory() as uow:
        ready_upload = await uow.uploads.mark_ready(
            upload_id,
            content_hash=f"sha256:{stored.sha256}",
            actual_size=stored.size,
        )
        try:
            await uow.commit()
        except Exception:
            log_warning(
                logger,
                (
                    "source_intake_upload_ready_commit_failed upload_id=%s "
                    "storage_key=%s actual_size=%s"
                ),
                upload_id,
                storage_key,
                stored.size,
                exc_info=True,
            )
            providers.metrics.increment_counter(
                "source_intake_upload_events_total",
                labels={"event": "ready_commit_failed"},
            )
            providers.metrics.observe_latency_ms(
                "source_intake_upload_register_latency_ms",
                (providers.monotonic_clock.monotonic_seconds() - started_at) * 1000,
                labels={"outcome": "ready_commit_failed"},
            )
            raise
    return ready_upload


async def create_ingestion_job(
    uow: CanonicalUnitOfWork,
    request: CreateIngestionJobRequest,
    *,
    runtime: SourceIntakeRuntime | None = None,
) -> IngestionJob:
    """Create an intake-stage ingestion job for a known series profile."""
    profile = await uow.series_profiles.get(request.series_profile_id)
    if profile is None:
        raise SeriesProfileNotFoundError(str(request.series_profile_id))
    providers = _source_intake_runtime(runtime)
    now = providers.clock()
    job = IngestionJob(
        id=providers.uuid_factory(),
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
    *,
    runtime: SourceIntakeRuntime | None = None,
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

    providers = _source_intake_runtime(runtime)
    source = IngestionJobSource(
        id=providers.uuid_factory(),
        ingestion_job_id=request.ingestion_job_id,
        attachment_kind=request.attachment_kind,
        upload_id=request.upload_id,
        source_uri=source_uri,
        source_type=request.source_type,
        weight=request.weight,
        metadata=request.metadata,
        created_at=providers.clock(),
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


async def get_upload(
    uow: CanonicalUnitOfWork,
    upload_id: uuid.UUID,
) -> Upload:
    """Fetch one upload or raise a source-intake not-found error."""
    upload = await uow.uploads.get(upload_id)
    if upload is None:
        raise UploadNotFoundError(str(upload_id))
    return upload


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


async def list_ingestion_job_sources(
    uow: CanonicalUnitOfWork,
    job_id: uuid.UUID,
    pagination: Pagination,
) -> IngestionJobSourcePage:
    """List source attachments for one ingestion job with total count."""
    job = await uow.ingestion_jobs.get(job_id)
    if job is None:
        raise IngestionJobNotFoundError(str(job_id))
    items = await uow.ingestion_job_sources.list_for_job_paged(
        job_id,
        limit=pagination.limit,
        offset=pagination.offset,
    )
    total = await uow.ingestion_job_sources.count_for_job(job_id)
    return IngestionJobSourcePage(items=items, total=total, pagination=pagination)


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


def _validate_declared_upload(
    request: UploadBytesRequest,
    payload_sha256: str | None = None,
) -> None:
    """Check client-declared size and hash against the supplied payload."""
    actual_size = len(request.payload)
    if actual_size != request.declared_size:
        raise UploadSizeMismatchError(str(request.declared_size))
    if request.declared_sha256 is None:
        return
    actual_hash = payload_sha256 or hashlib.sha256(request.payload).hexdigest()
    if request.declared_sha256 != actual_hash:
        raise UploadHashMismatchError(request.declared_sha256)


def _source_intake_runtime(
    runtime: SourceIntakeRuntime | None,
) -> SourceIntakeRuntime:
    """Return source-intake runtime providers with production defaults."""
    return source_intake_runtime(runtime)


async def _single_chunk_stream(payload: bytes) -> cabc.AsyncIterator[bytes]:
    """Yield a bytes payload through the object-store streaming port."""
    await asyncio.sleep(0)
    yield payload


_UPLOAD_ID_MISSING = "missing upload_id"
