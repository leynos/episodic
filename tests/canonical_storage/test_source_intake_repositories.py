"""Unit tests for source-intake SQLAlchemy repositories."""

from __future__ import annotations

import asyncio
import dataclasses as dc
import datetime as dt
import typing as typ
import uuid

import pytest
import sqlalchemy as sa

from episodic.canonical.domain import IngestionJobListFilters, IntakeState
from episodic.canonical.idempotency import (
    Acquired,
    Conflict,
    IdempotencyAcquireRequest,
    IdempotencyState,
    InFlight,
    Replay,
)
from episodic.canonical.ingestion_sources import AttachmentKind, IngestionJobSource
from episodic.canonical.storage import SqlAlchemyUnitOfWork
from episodic.canonical.storage.source_intake_models import IdempotencyRecordModel
from episodic.canonical.storage.source_intake_repositories import (
    SourceIntakeStorageRuntime,
    SqlAlchemyIdempotencyStore,
)
from episodic.canonical.uploads import Upload, UploadState
from episodic.observability import NoopMetrics, PerfCounterClock

if typ.TYPE_CHECKING:
    import collections.abc as cabc

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

    from episodic.canonical.domain import (
        CanonicalEpisode,
        IngestionJob,
        SeriesProfile,
        SourceDocument,
        TeiHeader,
    )


@dc.dataclass(frozen=True, slots=True)
class _RoundTripResult:
    """Values produced while persisting source-intake fixtures."""

    upload: Upload
    ready_upload: Upload
    transitioned: bool


@dc.dataclass(frozen=True, slots=True)
class _FetchedRoundTrip:
    """Values fetched back from source-intake repositories."""

    upload: Upload
    sources: cabc.Sequence[IngestionJobSource]
    job_ids: cabc.Sequence[uuid.UUID]
    total: int


@pytest.mark.asyncio
async def test_source_intake_repositories_round_trip(
    session_factory: object,
    episode_fixture: tuple[
        SeriesProfile,
        TeiHeader,
        CanonicalEpisode,
        IngestionJob,
        SourceDocument,
    ],
) -> None:
    """Upload and source-attachment repositories round-trip stored entities."""
    series, _, _, job, _ = episode_fixture
    factory = typ.cast("async_sessionmaker[AsyncSession]", session_factory)
    result = await _persist_round_trip_fixture(factory, episode_fixture)
    fetched = await _fetch_round_trip_fixture(
        factory,
        series_id=series.id,
        job_id=job.id,
        upload_id=result.upload.id,
    )

    assert result.transitioned is True
    assert result.ready_upload.state is UploadState.READY
    assert fetched.upload.content_hash == "sha256:abc123"
    assert fetched.sources[0].upload_id == result.upload.id
    assert fetched.job_ids == [job.id]
    assert fetched.total == 1


async def _persist_round_trip_fixture(
    factory: async_sessionmaker[AsyncSession],
    episode_fixture: tuple[
        SeriesProfile,
        TeiHeader,
        CanonicalEpisode,
        IngestionJob,
        SourceDocument,
    ],
) -> _RoundTripResult:
    """Persist source-intake fixture rows and return transition results."""
    series, header, episode, job, _ = episode_fixture
    upload = _make_upload()

    async with SqlAlchemyUnitOfWork(factory) as uow:
        await uow.series_profiles.add(series)
        await uow.tei_headers.add(header)
        await uow.flush()
        await uow.episodes.add(episode)
        await uow.ingestion_jobs.add(job)
        await uow.uploads.add(upload)
        ready_upload = await uow.uploads.mark_ready(
            upload.id,
            content_hash="sha256:abc123",
            actual_size=6,
        )
        source = IngestionJobSource(
            id=uuid.uuid4(),
            ingestion_job_id=job.id,
            attachment_kind=AttachmentKind.UPLOAD,
            upload_id=upload.id,
            source_uri=None,
            source_type="research_paper",
            weight=1.0,
            metadata={"language": "en"},
            created_at=upload.created_at,
        )
        await uow.ingestion_job_sources.add(source)
        transitioned = await uow.ingestion_jobs.transition_intake_state(
            job.id,
            from_state=IntakeState.AWAITING_SOURCES,
            to_state=IntakeState.READY_FOR_GENERATION,
        )
        await uow.commit()
    return _RoundTripResult(
        upload=upload,
        ready_upload=ready_upload,
        transitioned=transitioned,
    )


async def _fetch_round_trip_fixture(
    factory: async_sessionmaker[AsyncSession],
    *,
    series_id: uuid.UUID,
    job_id: uuid.UUID,
    upload_id: uuid.UUID,
) -> _FetchedRoundTrip:
    """Fetch persisted source-intake rows for assertions."""
    async with SqlAlchemyUnitOfWork(factory) as uow:
        fetched_upload = await uow.uploads.get(upload_id)
        fetched_sources = await uow.ingestion_job_sources.list_for_job_paged(
            job_id,
            limit=10,
            offset=0,
        )
        page = await uow.ingestion_jobs.list_paged(
            IngestionJobListFilters(
                series_profile_id=series_id,
                intake_state=IntakeState.READY_FOR_GENERATION,
            ),
            limit=10,
            offset=0,
        )
        total = await uow.ingestion_jobs.count(
            IngestionJobListFilters(
                series_profile_id=series_id,
                intake_state=IntakeState.READY_FOR_GENERATION,
            )
        )
    if fetched_upload is None:
        msg = f"Expected upload to round-trip: {upload_id}"
        raise AssertionError(msg)
    return _FetchedRoundTrip(
        upload=fetched_upload,
        sources=fetched_sources,
        job_ids=[item.id for item in page],
        total=total,
    )


def _make_upload() -> Upload:
    """Return one pending upload fixture."""
    now = dt.datetime.now(dt.UTC)
    return Upload(
        id=uuid.uuid4(),
        owner_principal_id="api-user",
        content_type="text/plain",
        declared_size=6,
        actual_size=None,
        declared_sha256=None,
        content_hash=None,
        storage_key=f"uploads/{uuid.uuid4()}",
        state=UploadState.PENDING,
        metadata={"language": "en"},
        created_at=now,
        updated_at=now,
    )


@pytest.mark.asyncio
async def test_sqlalchemy_idempotency_store_replays_and_conflicts(
    session_factory: object,
) -> None:
    """SQLAlchemy idempotency store returns domain-only outcomes."""
    factory = typ.cast("async_sessionmaker[AsyncSession]", session_factory)
    request = IdempotencyAcquireRequest(
        principal_id=None,
        operation="upload.create",
        idempotency_key="same-key",
        body_hash="body-a",
        expires_at=dt.datetime.now(dt.UTC) + dt.timedelta(hours=1),
    )

    async with SqlAlchemyUnitOfWork(factory) as uow:
        acquired = await uow.idempotency.acquire(request=request)
        assert not isinstance(acquired, Replay | Conflict | InFlight)
        await uow.idempotency.complete(
            record_id=acquired.record_id,
            serialised_outcome=b'{"ok":true}',
        )
        await uow.commit()

    async with SqlAlchemyUnitOfWork(factory) as uow:
        replay = await uow.idempotency.acquire(request=request)
        conflict = await uow.idempotency.acquire(
            request=IdempotencyAcquireRequest(
                principal_id=None,
                operation="upload.create",
                idempotency_key="same-key",
                body_hash="body-b",
                expires_at=dt.datetime.now(dt.UTC) + dt.timedelta(hours=1),
            )
        )

    assert isinstance(replay, Replay)
    assert replay.serialised_outcome == b'{"ok":true}'
    assert isinstance(conflict, Conflict)


@pytest.mark.asyncio
async def test_sqlalchemy_idempotency_store_uses_injected_time_and_ids(
    session_factory: object,
) -> None:
    """SQLAlchemy idempotency records use injected providers at the boundary."""
    factory = typ.cast("async_sessionmaker[AsyncSession]", session_factory)
    fixed_record_id = uuid.UUID("00000000-0000-4000-8000-000000000001")
    fixed_now = dt.datetime(2026, 6, 12, 1, 45, tzinfo=dt.UTC)
    request = IdempotencyAcquireRequest(
        principal_id="principal",
        operation="upload.create",
        idempotency_key="deterministic-key",
        body_hash="body-a",
        expires_at=fixed_now + dt.timedelta(hours=1),
    )

    async with factory() as session:
        store = SqlAlchemyIdempotencyStore(
            session,
            runtime=SourceIntakeStorageRuntime(
                clock=lambda: fixed_now,
                uuid_factory=lambda: fixed_record_id,
                metrics=NoopMetrics(),
                monotonic_clock=PerfCounterClock(),
            ),
        )
        acquired = await store.acquire(request=request)
        await session.commit()

    async with factory() as session:
        record = await session.get(IdempotencyRecordModel, fixed_record_id)

    assert isinstance(acquired, Acquired)
    assert acquired.record_id == fixed_record_id
    assert record is not None, "expected deterministic record to persist"
    assert record.created_at == fixed_now
    assert record.updated_at == fixed_now


@pytest.mark.asyncio
async def test_sqlalchemy_idempotency_store_concurrent_acquire_is_first_writer_wins(
    session_factory: object,
) -> None:
    """Concurrent acquires for one logical key converge on one stored row."""
    factory = typ.cast("async_sessionmaker[AsyncSession]", session_factory)
    request = IdempotencyAcquireRequest(
        principal_id="principal",
        operation="upload.create",
        idempotency_key=f"concurrent-{uuid.uuid4()}",
        body_hash="body-a",
        expires_at=dt.datetime.now(dt.UTC) + dt.timedelta(hours=1),
    )

    async def acquire() -> Acquired | Replay | Conflict | InFlight:
        async with SqlAlchemyUnitOfWork(factory) as uow:
            outcome = await uow.idempotency.acquire(request=request)
            await uow.commit()
            return outcome

    first, second = await asyncio.gather(acquire(), acquire())

    async with factory() as session:
        persisted_count = await session.scalar(
            sa
            .select(sa.func.count())
            .select_from(IdempotencyRecordModel)
            .where(IdempotencyRecordModel.idempotency_key == request.idempotency_key)
        )

    assert sum(isinstance(outcome, Acquired) for outcome in (first, second)) == 1
    assert sum(isinstance(outcome, InFlight) for outcome in (first, second)) == 1
    assert persisted_count == 1


@pytest.mark.asyncio
async def test_sqlalchemy_idempotency_store_reacquires_expired_in_flight_record(
    session_factory: object,
) -> None:
    """Expired in-flight records should not block a retry forever."""
    factory = typ.cast("async_sessionmaker[AsyncSession]", session_factory)
    expired_record_id = uuid.UUID("00000000-0000-4000-8000-000000000010")
    replacement_record_id = uuid.UUID("00000000-0000-4000-8000-000000000011")
    fixed_now = dt.datetime(2026, 6, 12, 2, 15, tzinfo=dt.UTC)
    request = IdempotencyAcquireRequest(
        principal_id="principal",
        operation="upload.create",
        idempotency_key="expired-key",
        body_hash="body-a",
        expires_at=fixed_now + dt.timedelta(hours=1),
    )

    async with factory() as session:
        session.add(
            IdempotencyRecordModel(
                id=expired_record_id,
                principal_id="principal",
                operation=request.operation,
                idempotency_key=request.idempotency_key,
                body_hash=request.body_hash,
                state=IdempotencyState.IN_FLIGHT,
                serialised_outcome=None,
                expires_at=fixed_now - dt.timedelta(seconds=1),
                created_at=fixed_now - dt.timedelta(hours=1),
                updated_at=fixed_now - dt.timedelta(hours=1),
            )
        )
        await session.commit()

    async with factory() as session:
        store = SqlAlchemyIdempotencyStore(
            session,
            runtime=SourceIntakeStorageRuntime(
                clock=lambda: fixed_now,
                uuid_factory=lambda: replacement_record_id,
                metrics=NoopMetrics(),
                monotonic_clock=PerfCounterClock(),
            ),
        )
        outcome = await store.acquire(request=request)
        await session.commit()

    async with factory() as session:
        expired_record = await session.get(IdempotencyRecordModel, expired_record_id)
        replacement_record = await session.get(
            IdempotencyRecordModel,
            replacement_record_id,
        )

    assert isinstance(outcome, Acquired)
    assert outcome.record_id == replacement_record_id
    assert expired_record is None
    assert replacement_record is not None
    assert replacement_record.expires_at == request.expires_at
