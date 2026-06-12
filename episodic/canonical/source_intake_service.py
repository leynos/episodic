"""Application services for source-intake REST workflows."""
# pylint: disable=too-many-lines

from __future__ import annotations

import asyncio
import collections.abc as cabc
import dataclasses as dc
import datetime as dt
import hashlib
import typing as typ
import uuid

from episodic.logging import get_logger, log_info, log_warning
from episodic.observability import NoopMetrics, PerfCounterClock

from .domain import IngestionJob, IngestionJobListFilters, IngestionStatus, IntakeState
from .ingestion_sources import AttachmentKind, IngestionJobSource
from .uploads import Upload, UploadState

if typ.TYPE_CHECKING:
    from episodic.observability import MetricsPort, MonotonicClockPort

    from .domain import JsonMapping
    from .object_store import ObjectStorePort, StoredObject
    from .pagination import Pagination
    from .unit_of_work_protocols import CanonicalUnitOfWork

    UowFactory = cabc.Callable[[], CanonicalUnitOfWork]


_UPLOAD_STORAGE_PREFIX = "uploads"
Clock = cabc.Callable[[], dt.datetime]
UuidFactory = cabc.Callable[[], uuid.UUID]
logger = get_logger(__name__)


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
class SourceIntakeRuntime:
    """Runtime providers used by source-intake command services."""

    clock: Clock
    uuid_factory: UuidFactory
    metrics: MetricsPort
    monotonic_clock: MonotonicClockPort


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
    *,
    runtime: SourceIntakeRuntime | None = None,
) -> Upload:
    """Persist upload bytes after committing a recoverable pending row."""
    _validate_declared_upload(request)
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
    stored = await _store_upload_bytes(
        object_store,
        upload_id,
        storage_key,
        request,
        providers,
    )
    ready_upload = await _commit_ready_upload(
        uow_factory,
        upload_id,
        storage_key,
        stored,
        started_at,
        providers,
    )
    log_info(
        logger,
        "source_intake_upload_ready upload_id=%s storage_key=%s actual_size=%s",
        upload_id,
        storage_key,
        stored.size,
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
        (
            "source_intake_upload_pending upload_id=%s owner_principal_id=%s "
            "content_type=%s declared_size=%s"
        ),
        upload.id,
        upload.owner_principal_id,
        upload.content_type,
        upload.declared_size,
    )
    providers.metrics.increment_counter(
        "source_intake_upload_events_total",
        labels={"event": "pending_committed"},
    )


async def _store_upload_bytes(  # noqa: PLR0913, PLR0917  # pylint: disable=too-many-arguments,too-many-positional-arguments
    object_store: ObjectStorePort,
    upload_id: uuid.UUID,
    storage_key: str,
    request: UploadBytesRequest,
    providers: SourceIntakeRuntime,
) -> StoredObject:
    """Store upload bytes through the object-store port."""
    stored = await object_store.put(
        storage_key,
        _single_chunk_stream(request.payload),
        max_bytes=request.max_bytes,
    )
    log_info(
        logger,
        (
            "source_intake_upload_stored upload_id=%s storage_key=%s "
            "actual_size=%s content_hash=%s"
        ),
        upload_id,
        storage_key,
        stored.size,
        f"sha256:{stored.sha256}",
    )
    providers.metrics.increment_counter(
        "source_intake_upload_events_total",
        labels={"event": "object_stored"},
    )
    return stored


async def _commit_ready_upload(  # noqa: PLR0913, PLR0917  # pylint: disable=too-many-arguments,too-many-positional-arguments
    uow_factory: UowFactory,
    upload_id: uuid.UUID,
    storage_key: str,
    stored: StoredObject,
    started_at: float,
    providers: SourceIntakeRuntime,
) -> Upload:
    """Mark a stored upload ready or preserve recovery signals on failure."""
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


def _utc_now() -> dt.datetime:
    """Return the current UTC timestamp for source-intake entities."""
    return dt.datetime.now(dt.UTC)


def _new_uuid() -> uuid.UUID:
    """Return a new source-intake identifier."""
    return uuid.uuid4()


def _source_intake_runtime(
    runtime: SourceIntakeRuntime | None,
) -> SourceIntakeRuntime:
    """Return source-intake runtime providers with production defaults."""
    if runtime is not None:
        return runtime
    return SourceIntakeRuntime(
        clock=_utc_now,
        uuid_factory=_new_uuid,
        metrics=NoopMetrics(),
        monotonic_clock=PerfCounterClock(),
    )


async def _single_chunk_stream(payload: bytes) -> cabc.AsyncIterator[bytes]:
    """Yield a bytes payload through the object-store streaming port."""
    await asyncio.sleep(0)
    yield payload


_UPLOAD_ID_MISSING = "missing upload_id"
