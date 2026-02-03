"""SQLAlchemy persistence adapters for canonical content."""

from __future__ import annotations

import datetime as dt  # noqa: TC003 - SQLAlchemy evaluates annotations at runtime.
import typing as typ
import uuid  # noqa: TC003 - SQLAlchemy evaluates annotations at runtime.

import sqlalchemy as sa
from sqlalchemy import orm
from sqlalchemy.dialects import postgresql

from episodic.logging import get_logger, log_info

from .domain import (
    ApprovalEvent,
    ApprovalState,
    CanonicalEpisode,
    EpisodeStatus,
    IngestionJob,
    IngestionStatus,
    SeriesProfile,
    SourceDocument,
    TeiHeader,
)
from .ports import (
    ApprovalEventRepository,
    CanonicalUnitOfWork,
    EpisodeRepository,
    IngestionJobRepository,
    SeriesProfileRepository,
    SourceDocumentRepository,
    TeiHeaderRepository,
)

if typ.TYPE_CHECKING:
    from types import TracebackType

    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = get_logger(__name__)


class Base(orm.DeclarativeBase):
    """Base for canonical SQLAlchemy models."""


EPISODE_STATUS = sa.Enum(
    EpisodeStatus,
    name="episode_status",
    values_callable=lambda enum_cls: [item.value for item in enum_cls],
)
APPROVAL_STATE = sa.Enum(
    ApprovalState,
    name="approval_state",
    values_callable=lambda enum_cls: [item.value for item in enum_cls],
)
INGESTION_STATUS = sa.Enum(
    IngestionStatus,
    name="ingestion_status",
    values_callable=lambda enum_cls: [item.value for item in enum_cls],
)


class SeriesProfileRecord(Base):
    """SQLAlchemy model for series profiles."""

    __tablename__ = "series_profiles"

    id: orm.Mapped[uuid.UUID] = orm.mapped_column(
        postgresql.UUID(as_uuid=True),
        primary_key=True,
    )
    slug: orm.Mapped[str] = orm.mapped_column(sa.String(160), unique=True)
    title: orm.Mapped[str] = orm.mapped_column(sa.String(240))
    description: orm.Mapped[str | None] = orm.mapped_column(sa.Text, nullable=True)
    configuration: orm.Mapped[dict[str, typ.Any]] = orm.mapped_column(
        postgresql.JSONB,
        default=dict,
    )
    created_at: orm.Mapped[dt.datetime] = orm.mapped_column(
        sa.DateTime(timezone=True),
        server_default=sa.func.now(),
    )
    updated_at: orm.Mapped[dt.datetime] = orm.mapped_column(
        sa.DateTime(timezone=True),
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
    )


class TeiHeaderRecord(Base):
    """SQLAlchemy model for parsed TEI headers."""

    __tablename__ = "tei_headers"

    id: orm.Mapped[uuid.UUID] = orm.mapped_column(
        postgresql.UUID(as_uuid=True),
        primary_key=True,
    )
    title: orm.Mapped[str] = orm.mapped_column(sa.String(240))
    payload: orm.Mapped[dict[str, typ.Any]] = orm.mapped_column(
        postgresql.JSONB,
    )
    raw_xml: orm.Mapped[str] = orm.mapped_column(sa.Text)
    created_at: orm.Mapped[dt.datetime] = orm.mapped_column(
        sa.DateTime(timezone=True),
        server_default=sa.func.now(),
    )
    updated_at: orm.Mapped[dt.datetime] = orm.mapped_column(
        sa.DateTime(timezone=True),
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
    )


class EpisodeRecord(Base):
    """SQLAlchemy model for canonical episodes."""

    __tablename__ = "episodes"

    id: orm.Mapped[uuid.UUID] = orm.mapped_column(
        postgresql.UUID(as_uuid=True),
        primary_key=True,
    )
    series_profile_id: orm.Mapped[uuid.UUID] = orm.mapped_column(
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("series_profiles.id"),
    )
    tei_header_id: orm.Mapped[uuid.UUID] = orm.mapped_column(
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("tei_headers.id"),
    )
    title: orm.Mapped[str] = orm.mapped_column(sa.String(240))
    tei_xml: orm.Mapped[str] = orm.mapped_column(sa.Text)
    status: orm.Mapped[EpisodeStatus] = orm.mapped_column(EPISODE_STATUS)
    approval_state: orm.Mapped[ApprovalState] = orm.mapped_column(APPROVAL_STATE)
    created_at: orm.Mapped[dt.datetime] = orm.mapped_column(
        sa.DateTime(timezone=True),
        server_default=sa.func.now(),
    )
    updated_at: orm.Mapped[dt.datetime] = orm.mapped_column(
        sa.DateTime(timezone=True),
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
    )


class IngestionJobRecord(Base):
    """SQLAlchemy model for ingestion jobs."""

    __tablename__ = "ingestion_jobs"

    id: orm.Mapped[uuid.UUID] = orm.mapped_column(
        postgresql.UUID(as_uuid=True),
        primary_key=True,
    )
    series_profile_id: orm.Mapped[uuid.UUID] = orm.mapped_column(
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("series_profiles.id"),
    )
    target_episode_id: orm.Mapped[uuid.UUID | None] = orm.mapped_column(
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("episodes.id"),
        nullable=True,
    )
    status: orm.Mapped[IngestionStatus] = orm.mapped_column(INGESTION_STATUS)
    requested_at: orm.Mapped[dt.datetime] = orm.mapped_column(
        sa.DateTime(timezone=True),
    )
    started_at: orm.Mapped[dt.datetime | None] = orm.mapped_column(
        sa.DateTime(timezone=True),
        nullable=True,
    )
    completed_at: orm.Mapped[dt.datetime | None] = orm.mapped_column(
        sa.DateTime(timezone=True),
        nullable=True,
    )
    error_message: orm.Mapped[str | None] = orm.mapped_column(sa.Text, nullable=True)
    created_at: orm.Mapped[dt.datetime] = orm.mapped_column(
        sa.DateTime(timezone=True),
        server_default=sa.func.now(),
    )
    updated_at: orm.Mapped[dt.datetime] = orm.mapped_column(
        sa.DateTime(timezone=True),
        server_default=sa.func.now(),
        onupdate=sa.func.now(),
    )


class SourceDocumentRecord(Base):
    """SQLAlchemy model for source documents."""

    __tablename__ = "source_documents"

    id: orm.Mapped[uuid.UUID] = orm.mapped_column(
        postgresql.UUID(as_uuid=True),
        primary_key=True,
    )
    ingestion_job_id: orm.Mapped[uuid.UUID] = orm.mapped_column(
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("ingestion_jobs.id"),
    )
    canonical_episode_id: orm.Mapped[uuid.UUID | None] = orm.mapped_column(
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("episodes.id"),
        nullable=True,
    )
    source_type: orm.Mapped[str] = orm.mapped_column(sa.String(120))
    source_uri: orm.Mapped[str] = orm.mapped_column(sa.Text)
    weight: orm.Mapped[float] = orm.mapped_column(sa.Float)
    content_hash: orm.Mapped[str] = orm.mapped_column(sa.String(128))
    metadata_payload: orm.Mapped[dict[str, typ.Any]] = orm.mapped_column(
        "metadata",
        postgresql.JSONB,
        default=dict,
    )
    created_at: orm.Mapped[dt.datetime] = orm.mapped_column(
        sa.DateTime(timezone=True),
        server_default=sa.func.now(),
    )

    __table_args__ = (
        sa.CheckConstraint(
            "weight >= 0 AND weight <= 1",
            name="ck_source_documents_weight",
        ),
    )


class ApprovalEventRecord(Base):
    """SQLAlchemy model for approval events."""

    __tablename__ = "approval_events"

    id: orm.Mapped[uuid.UUID] = orm.mapped_column(
        postgresql.UUID(as_uuid=True),
        primary_key=True,
    )
    episode_id: orm.Mapped[uuid.UUID] = orm.mapped_column(
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey("episodes.id"),
    )
    actor: orm.Mapped[str | None] = orm.mapped_column(sa.String(200), nullable=True)
    from_state: orm.Mapped[ApprovalState | None] = orm.mapped_column(
        APPROVAL_STATE,
        nullable=True,
    )
    to_state: orm.Mapped[ApprovalState] = orm.mapped_column(APPROVAL_STATE)
    note: orm.Mapped[str | None] = orm.mapped_column(sa.Text, nullable=True)
    payload: orm.Mapped[dict[str, typ.Any]] = orm.mapped_column(
        postgresql.JSONB,
        default=dict,
    )
    created_at: orm.Mapped[dt.datetime] = orm.mapped_column(
        sa.DateTime(timezone=True),
        server_default=sa.func.now(),
    )


def _series_profile_from_record(record: SeriesProfileRecord) -> SeriesProfile:
    return SeriesProfile(
        id=record.id,
        slug=record.slug,
        title=record.title,
        description=record.description,
        configuration=record.configuration,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _tei_header_from_record(record: TeiHeaderRecord) -> TeiHeader:
    return TeiHeader(
        id=record.id,
        title=record.title,
        payload=record.payload,
        raw_xml=record.raw_xml,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _episode_from_record(record: EpisodeRecord) -> CanonicalEpisode:
    return CanonicalEpisode(
        id=record.id,
        series_profile_id=record.series_profile_id,
        tei_header_id=record.tei_header_id,
        title=record.title,
        tei_xml=record.tei_xml,
        status=record.status,
        approval_state=record.approval_state,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _ingestion_job_from_record(record: IngestionJobRecord) -> IngestionJob:
    return IngestionJob(
        id=record.id,
        series_profile_id=record.series_profile_id,
        target_episode_id=record.target_episode_id,
        status=record.status,
        requested_at=record.requested_at,
        started_at=record.started_at,
        completed_at=record.completed_at,
        error_message=record.error_message,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _source_document_from_record(record: SourceDocumentRecord) -> SourceDocument:
    return SourceDocument(
        id=record.id,
        ingestion_job_id=record.ingestion_job_id,
        canonical_episode_id=record.canonical_episode_id,
        source_type=record.source_type,
        source_uri=record.source_uri,
        weight=record.weight,
        content_hash=record.content_hash,
        metadata=record.metadata_payload,
        created_at=record.created_at,
    )


def _approval_event_from_record(record: ApprovalEventRecord) -> ApprovalEvent:
    return ApprovalEvent(
        id=record.id,
        episode_id=record.episode_id,
        actor=record.actor,
        from_state=record.from_state,
        to_state=record.to_state,
        note=record.note,
        payload=record.payload,
        created_at=record.created_at,
    )


class SqlAlchemySeriesProfileRepository(SeriesProfileRepository):
    """SQLAlchemy-backed series profile repository."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, profile: SeriesProfile) -> None:
        """Add a series profile record."""
        self._session.add(
            SeriesProfileRecord(
                id=profile.id,
                slug=profile.slug,
                title=profile.title,
                description=profile.description,
                configuration=profile.configuration,
                created_at=profile.created_at,
                updated_at=profile.updated_at,
            )
        )

    async def get(self, profile_id: uuid.UUID) -> SeriesProfile | None:
        """Fetch a series profile by identifier."""
        result = await self._session.execute(
            sa.select(SeriesProfileRecord).where(SeriesProfileRecord.id == profile_id)
        )
        record = result.scalar_one_or_none()
        if record is None:
            return None
        return _series_profile_from_record(record)

    async def get_by_slug(self, slug: str) -> SeriesProfile | None:
        """Fetch a series profile by slug."""
        result = await self._session.execute(
            sa.select(SeriesProfileRecord).where(SeriesProfileRecord.slug == slug)
        )
        record = result.scalar_one_or_none()
        if record is None:
            return None
        return _series_profile_from_record(record)


class SqlAlchemyTeiHeaderRepository(TeiHeaderRepository):
    """SQLAlchemy-backed TEI header repository."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, header: TeiHeader) -> None:
        """Add a TEI header record."""
        self._session.add(
            TeiHeaderRecord(
                id=header.id,
                title=header.title,
                payload=header.payload,
                raw_xml=header.raw_xml,
                created_at=header.created_at,
                updated_at=header.updated_at,
            )
        )

    async def get(self, header_id: uuid.UUID) -> TeiHeader | None:
        """Fetch a TEI header by identifier."""
        result = await self._session.execute(
            sa.select(TeiHeaderRecord).where(TeiHeaderRecord.id == header_id)
        )
        record = result.scalar_one_or_none()
        if record is None:
            return None
        return _tei_header_from_record(record)


class SqlAlchemyEpisodeRepository(EpisodeRepository):
    """SQLAlchemy-backed canonical episode repository."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, episode: CanonicalEpisode) -> None:
        """Add a canonical episode record."""
        self._session.add(
            EpisodeRecord(
                id=episode.id,
                series_profile_id=episode.series_profile_id,
                tei_header_id=episode.tei_header_id,
                title=episode.title,
                tei_xml=episode.tei_xml,
                status=episode.status,
                approval_state=episode.approval_state,
                created_at=episode.created_at,
                updated_at=episode.updated_at,
            )
        )

    async def get(self, episode_id: uuid.UUID) -> CanonicalEpisode | None:
        """Fetch a canonical episode by identifier."""
        result = await self._session.execute(
            sa.select(EpisodeRecord).where(EpisodeRecord.id == episode_id)
        )
        record = result.scalar_one_or_none()
        if record is None:
            return None
        return _episode_from_record(record)


class SqlAlchemyIngestionJobRepository(IngestionJobRepository):
    """SQLAlchemy-backed ingestion job repository."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, job: IngestionJob) -> None:
        """Add an ingestion job record."""
        self._session.add(
            IngestionJobRecord(
                id=job.id,
                series_profile_id=job.series_profile_id,
                target_episode_id=job.target_episode_id,
                status=job.status,
                requested_at=job.requested_at,
                started_at=job.started_at,
                completed_at=job.completed_at,
                error_message=job.error_message,
                created_at=job.created_at,
                updated_at=job.updated_at,
            )
        )

    async def get(self, job_id: uuid.UUID) -> IngestionJob | None:
        """Fetch an ingestion job by identifier."""
        result = await self._session.execute(
            sa.select(IngestionJobRecord).where(IngestionJobRecord.id == job_id)
        )
        record = result.scalar_one_or_none()
        if record is None:
            return None
        return _ingestion_job_from_record(record)


class SqlAlchemySourceDocumentRepository(SourceDocumentRepository):
    """SQLAlchemy-backed source document repository."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, document: SourceDocument) -> None:
        """Add a source document record."""
        self._session.add(
            SourceDocumentRecord(
                id=document.id,
                ingestion_job_id=document.ingestion_job_id,
                canonical_episode_id=document.canonical_episode_id,
                source_type=document.source_type,
                source_uri=document.source_uri,
                weight=document.weight,
                content_hash=document.content_hash,
                metadata_payload=document.metadata,
                created_at=document.created_at,
            )
        )

    async def list_for_job(self, job_id: uuid.UUID) -> list[SourceDocument]:
        """List source documents for an ingestion job."""
        result = await self._session.execute(
            sa.select(SourceDocumentRecord).where(
                SourceDocumentRecord.ingestion_job_id == job_id
            )
        )
        return [_source_document_from_record(row) for row in result.scalars()]


class SqlAlchemyApprovalEventRepository(ApprovalEventRepository):
    """SQLAlchemy-backed approval event repository."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, event: ApprovalEvent) -> None:
        """Add an approval event record."""
        self._session.add(
            ApprovalEventRecord(
                id=event.id,
                episode_id=event.episode_id,
                actor=event.actor,
                from_state=event.from_state,
                to_state=event.to_state,
                note=event.note,
                payload=event.payload,
                created_at=event.created_at,
            )
        )

    async def list_for_episode(
        self,
        episode_id: uuid.UUID,
    ) -> list[ApprovalEvent]:
        """List approval events for an episode."""
        result = await self._session.execute(
            sa.select(ApprovalEventRecord).where(
                ApprovalEventRecord.episode_id == episode_id
            )
        )
        return [_approval_event_from_record(row) for row in result.scalars()]


class SqlAlchemyUnitOfWork(CanonicalUnitOfWork):
    """Async unit-of-work backed by SQLAlchemy sessions."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self._session: AsyncSession | None = None

    async def __aenter__(self) -> SqlAlchemyUnitOfWork:
        """Open a unit-of-work session."""
        self._session = self._session_factory()
        self.series_profiles = SqlAlchemySeriesProfileRepository(self._session)
        self.tei_headers = SqlAlchemyTeiHeaderRepository(self._session)
        self.episodes = SqlAlchemyEpisodeRepository(self._session)
        self.ingestion_jobs = SqlAlchemyIngestionJobRepository(self._session)
        self.source_documents = SqlAlchemySourceDocumentRepository(self._session)
        self.approval_events = SqlAlchemyApprovalEventRepository(self._session)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Close the unit-of-work session."""
        if self._session is None:
            return
        if exc is not None:
            await self._session.rollback()
        await self._session.close()

    async def commit(self) -> None:
        """Commit the current unit-of-work session."""
        if self._session is None:
            msg = "Session not initialised for unit of work."
            raise RuntimeError(msg)
        await self._session.commit()
        log_info(logger, "Committed canonical unit of work.")

    async def flush(self) -> None:
        """Flush pending unit-of-work changes."""
        if self._session is None:
            msg = "Session not initialised for unit of work."
            raise RuntimeError(msg)
        await self._session.flush()

    async def rollback(self) -> None:
        """Roll back the current unit-of-work session."""
        if self._session is None:
            msg = "Session not initialised for unit of work."
            raise RuntimeError(msg)
        await self._session.rollback()
