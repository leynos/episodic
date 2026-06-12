"""SQLAlchemy repositories for source-intake entities."""
# pylint: disable=too-many-lines

from __future__ import annotations

import collections.abc as cabc
import dataclasses as dc
import datetime as dt
import typing as typ
import uuid

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError

from episodic.canonical.idempotency import (
    Acquired,
    Conflict,
    IdempotencyAcquireRequest,
    IdempotencyOutcome,
    IdempotencyState,
    InFlight,
    Replay,
)
from episodic.canonical.upload_protocols import (
    IdempotencyStore,
    IngestionJobSourceRepository,
    UploadRepository,
)
from episodic.canonical.uploads import UploadState
from episodic.logging import get_logger, log_info, log_warning
from episodic.observability import (
    MetricsPort,
    MonotonicClockPort,
    NoopMetrics,
    PerfCounterClock,
)

from .repository_base import _RepositoryBase
from .source_intake_mappers import (
    _idempotency_record_from_record,
    _ingestion_job_source_from_record,
    _ingestion_job_source_to_record,
    _principal_to_record,
    _upload_from_record,
    _upload_to_record,
)
from .source_intake_models import (
    IdempotencyRecordModel,
    IngestionJobSourceRecord,
    UploadRecord,
)

if typ.TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from episodic.canonical.idempotency import IdempotencyRecord
    from episodic.canonical.ingestion_sources import IngestionJobSource
    from episodic.canonical.uploads import Upload


Clock = cabc.Callable[[], dt.datetime]
UuidFactory = cabc.Callable[[], uuid.UUID]
logger = get_logger(__name__)


@dc.dataclass(frozen=True, slots=True)
class SourceIntakeStorageRuntime:
    """Runtime providers used by source-intake SQLAlchemy adapters."""

    clock: Clock
    uuid_factory: UuidFactory
    metrics: MetricsPort
    monotonic_clock: MonotonicClockPort


class SqlAlchemyUploadRepository(_RepositoryBase, UploadRepository):
    """Persist upload metadata using SQLAlchemy."""

    async def add(self, upload: Upload) -> None:
        """Persist an upload metadata record."""
        await self._add_record(_upload_to_record(upload))

    async def get(self, upload_id: uuid.UUID) -> Upload | None:
        """Fetch an upload by identifier."""
        return await self._get_one_or_none(
            UploadRecord,
            UploadRecord.id == upload_id,
            _upload_from_record,
        )

    async def mark_ready(
        self,
        upload_id: uuid.UUID,
        *,
        content_hash: str,
        actual_size: int,
    ) -> Upload:
        """Mark an upload as ready after object-store persistence."""
        await self._session.execute(
            sa
            .update(UploadRecord)
            .where(UploadRecord.id == upload_id)
            .values(
                content_hash=content_hash,
                actual_size=actual_size,
                state=UploadState.READY,
                updated_at=sa.func.now(),
            )
        )
        await self._session.flush()
        upload = await self.get(upload_id)
        if upload is None:
            msg = f"Upload not found after ready transition: {upload_id}"
            raise LookupError(msg)
        return upload

    async def mark_failed(self, upload_id: uuid.UUID, reason: str) -> Upload:
        """Mark an upload as failed."""
        del reason
        await self._session.execute(
            sa
            .update(UploadRecord)
            .where(UploadRecord.id == upload_id)
            .values(state=UploadState.FAILED, updated_at=sa.func.now())
        )
        await self._session.flush()
        upload = await self.get(upload_id)
        if upload is None:
            msg = f"Upload not found after failed transition: {upload_id}"
            raise LookupError(msg)
        return upload


class SqlAlchemyIngestionJobSourceRepository(
    _RepositoryBase,
    IngestionJobSourceRepository,
):
    """Persist pre-generation source attachments using SQLAlchemy."""

    async def add(self, source: IngestionJobSource) -> None:
        """Persist a source attachment."""
        await self._add_record(_ingestion_job_source_to_record(source))

    async def get(self, source_id: uuid.UUID) -> IngestionJobSource | None:
        """Fetch a source attachment by identifier."""
        return await self._get_one_or_none(
            IngestionJobSourceRecord,
            IngestionJobSourceRecord.id == source_id,
            _ingestion_job_source_from_record,
        )

    async def list_for_job_paged(
        self,
        job_id: uuid.UUID,
        *,
        limit: int,
        offset: int,
    ) -> cabc.Sequence[IngestionJobSource]:
        """List source attachments for one ingestion job."""
        statement = (
            sa
            .select(IngestionJobSourceRecord)
            .where(IngestionJobSourceRecord.ingestion_job_id == job_id)
            .order_by(IngestionJobSourceRecord.created_at, IngestionJobSourceRecord.id)
            .limit(limit)
            .offset(offset)
        )
        result = await self._session.execute(statement)
        return [_ingestion_job_source_from_record(row) for row in result.scalars()]

    async def count_for_job(self, job_id: uuid.UUID) -> int:
        """Count source attachments for one ingestion job."""
        result = await self._session.execute(
            sa
            .select(sa.func.count())
            .select_from(IngestionJobSourceRecord)
            .where(IngestionJobSourceRecord.ingestion_job_id == job_id)
        )
        return result.scalar_one()


class SqlAlchemyIdempotencyStore(_RepositoryBase, IdempotencyStore):
    """Persist idempotency records with domain-only outcomes."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        runtime: SourceIntakeStorageRuntime | None = None,
    ) -> None:
        self._session = session
        self._runtime = source_intake_storage_runtime(runtime)

    async def _insert_in_flight(
        self,
        *,
        request: IdempotencyAcquireRequest,
        record_id: uuid.UUID,
        now: dt.datetime,
    ) -> IdempotencyRecordModel | None:
        """Insert an in-flight idempotency record or return the conflicting row."""
        try:
            async with self._session.begin_nested():
                self._session.add(
                    IdempotencyRecordModel(
                        id=record_id,
                        principal_id=_principal_to_record(request.principal_id),
                        operation=request.operation,
                        idempotency_key=request.idempotency_key,
                        body_hash=request.body_hash,
                        state=IdempotencyState.IN_FLIGHT,
                        serialised_outcome=None,
                        expires_at=request.expires_at,
                        created_at=now,
                        updated_at=now,
                    )
                )
                await self._session.flush()
        except IntegrityError:
            log_warning(
                logger,
                ("source_intake_idempotency_acquire_conflict operation=%s"),
                request.operation,
                exc_info=True,
            )
            record = await self._get_record(
                principal_id=request.principal_id,
                operation=request.operation,
                idempotency_key=request.idempotency_key,
            )
            if record is None:
                raise
            return record
        return None

    async def acquire(
        self,
        *,
        request: IdempotencyAcquireRequest,
    ) -> IdempotencyOutcome:
        """Acquire or inspect an idempotency record."""
        started_at = self._runtime.monotonic_clock.monotonic_seconds()
        record = await self._get_record(
            principal_id=request.principal_id,
            operation=request.operation,
            idempotency_key=request.idempotency_key,
        )
        now = self._runtime.clock()
        if record is not None and record.expires_at <= now:
            await self._session.delete(record)
            await self._session.flush()
            record = None
        if record is None:
            record_id = self._runtime.uuid_factory()
            record = await self._insert_in_flight(
                request=request,
                record_id=record_id,
                now=now,
            )
            if record is None:
                log_info(
                    logger,
                    ("source_intake_idempotency_acquired record_id=%s operation=%s"),
                    record_id,
                    request.operation,
                )
                self._record_acquire_metrics(started_at, "acquired")
                return Acquired(record_id)
        outcome = _idempotency_outcome_for_record(record, request.body_hash)
        outcome_label = _outcome_metric_label(outcome)
        log_info(
            logger,
            ("source_intake_idempotency_outcome outcome=%s operation=%s"),
            outcome_label,
            request.operation,
        )
        self._record_acquire_metrics(started_at, outcome_label)
        return outcome

    def _record_acquire_metrics(self, started_at: float, outcome: str) -> None:
        """Record bounded idempotency acquire metrics."""
        self._runtime.metrics.increment_counter(
            "source_intake_idempotency_acquire_total",
            labels={"outcome": outcome},
        )
        self._runtime.metrics.observe_latency_ms(
            "source_intake_idempotency_acquire_latency_ms",
            (self._runtime.monotonic_clock.monotonic_seconds() - started_at) * 1000,
            labels={"outcome": outcome},
        )

    async def complete(
        self,
        *,
        record_id: uuid.UUID,
        serialised_outcome: bytes,
    ) -> None:
        """Store an opaque completed outcome for replay."""
        await self._session.execute(
            sa
            .update(IdempotencyRecordModel)
            .where(IdempotencyRecordModel.id == record_id)
            .values(
                state=IdempotencyState.COMPLETED,
                serialised_outcome=serialised_outcome,
                updated_at=sa.func.now(),
            )
        )

    async def fail(self, *, record_id: uuid.UUID) -> None:
        """Delete the IN_FLIGHT record so the client can retry immediately."""
        await self._session.execute(
            sa.delete(IdempotencyRecordModel).where(
                IdempotencyRecordModel.id == record_id
            )
        )

    async def lookup(
        self,
        *,
        principal_id: str | None,
        operation: str,
        idempotency_key: str,
    ) -> IdempotencyRecord | None:
        """Fetch an idempotency record by its logical key."""
        record = await self._get_record(
            principal_id=principal_id,
            operation=operation,
            idempotency_key=idempotency_key,
        )
        return None if record is None else _idempotency_record_from_record(record)

    async def _get_record(
        self,
        *,
        principal_id: str | None,
        operation: str,
        idempotency_key: str,
    ) -> IdempotencyRecordModel | None:
        """Fetch one raw idempotency row by logical key."""
        result = await self._session.execute(
            sa.select(IdempotencyRecordModel).where(
                sa.and_(
                    IdempotencyRecordModel.principal_id
                    == _principal_to_record(principal_id),
                    IdempotencyRecordModel.operation == operation,
                    IdempotencyRecordModel.idempotency_key == idempotency_key,
                )
            )
        )
        return result.scalar_one_or_none()


def _idempotency_outcome_for_record(
    record: IdempotencyRecordModel,
    body_hash: str,
) -> IdempotencyOutcome:
    """Map an existing idempotency record to the acquire outcome."""
    if record.body_hash != body_hash:
        return Conflict(record.id)
    if record.state is IdempotencyState.COMPLETED:
        if record.serialised_outcome is None:
            msg = f"Completed idempotency record lacks outcome: {record.id}"
            raise RuntimeError(msg)
        return Replay(record.serialised_outcome)
    return InFlight(record.id)


def _outcome_metric_label(outcome: IdempotencyOutcome) -> str:
    """Return a bounded label for idempotency acquire outcomes."""
    if isinstance(outcome, Replay):
        return "replay"
    if isinstance(outcome, Conflict):
        return "conflict"
    if isinstance(outcome, InFlight):
        return "in_flight"
    return "acquired"


def _utc_now() -> dt.datetime:
    """Return the current UTC timestamp for idempotency records."""
    return dt.datetime.now(dt.UTC)


def _new_uuid() -> uuid.UUID:
    """Return a new idempotency record identifier."""
    return uuid.uuid4()


def source_intake_storage_runtime(
    runtime: SourceIntakeStorageRuntime | None,
    *,
    metrics: MetricsPort | None = None,
    monotonic_clock: MonotonicClockPort | None = None,
) -> SourceIntakeStorageRuntime:
    """Return SQLAlchemy source-intake providers with production defaults."""
    if runtime is not None:
        return runtime
    return SourceIntakeStorageRuntime(
        clock=_utc_now,
        uuid_factory=_new_uuid,
        metrics=NoopMetrics() if metrics is None else metrics,
        monotonic_clock=PerfCounterClock()
        if monotonic_clock is None
        else monotonic_clock,
    )
