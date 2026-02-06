"""SQLAlchemy repositories for canonical content.

This module implements repository adapters that translate domain entities to
SQLAlchemy ORM records. Repositories operate within a supplied async session
and are intended to be composed through the canonical unit-of-work.
"""

from __future__ import annotations

import typing as typ
from typing import (  # noqa: ICN003, UP035  # TODO(@codex): https://github.com/leynos/episodic/pull/14 - review requirement.
    Any,
    Callable,
    TypeVar,
)

import sqlalchemy as sa

from episodic.canonical.ports import (
    ApprovalEventRepository,
    EpisodeRepository,
    IngestionJobRepository,
    SeriesProfileRepository,
    SourceDocumentRepository,
    TeiHeaderRepository,
)

from .mappers import (
    _approval_event_from_record,
    _episode_from_record,
    _ingestion_job_from_record,
    _series_profile_from_record,
    _source_document_from_record,
    _tei_header_from_record,
)
from .models import (
    ApprovalEventRecord,
    EpisodeRecord,
    IngestionJobRecord,
    SeriesProfileRecord,
    SourceDocumentRecord,
    TeiHeaderRecord,
)

if typ.TYPE_CHECKING:
    import uuid

    from sqlalchemy.ext.asyncio import AsyncSession

    from episodic.canonical.domain import (
        ApprovalEvent,
        CanonicalEpisode,
        IngestionJob,
        SeriesProfile,
        SourceDocument,
        TeiHeader,
    )

RecordT = TypeVar("RecordT")
DomainT = TypeVar("DomainT")


class _RepositoryBase:
    """Shared helpers for SQLAlchemy repositories."""

    _session: AsyncSession

    async def _get_one_or_none(
        self,
        record_type: type[RecordT],
        where_clause: Any,  # noqa: ANN401  # TODO(@codex): https://github.com/leynos/episodic/pull/14 - SQLAlchemy clause typing.
        mapper: Callable[[RecordT], DomainT],
    ) -> DomainT | None:
        result = await self._session.execute(sa.select(record_type).where(where_clause))
        record = result.scalar_one_or_none()
        if record is None:
            return None
        return mapper(record)


class SqlAlchemySeriesProfileRepository(_RepositoryBase, SeriesProfileRepository):
    """Persist series profiles using SQLAlchemy."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, profile: SeriesProfile) -> None:
        """Add a series profile record.

        Parameters
        ----------
        profile : SeriesProfile
            Series profile domain entity to persist.

        """
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
        """Fetch a series profile by identifier.

        Parameters
        ----------
        profile_id : uuid.UUID
            Identifier of the series profile to fetch.

        Returns
        -------
        SeriesProfile | None
            The matched series profile, or ``None`` if no match exists.
        """
        return await self._get_one_or_none(
            SeriesProfileRecord,
            SeriesProfileRecord.id == profile_id,
            _series_profile_from_record,
        )

    async def get_by_slug(self, slug: str) -> SeriesProfile | None:
        """Fetch a series profile by slug.

        Parameters
        ----------
        slug : str
            Slug to match against the stored series profiles.

        Returns
        -------
        SeriesProfile | None
            The matched series profile, or ``None`` if no match exists.
        """
        return await self._get_one_or_none(
            SeriesProfileRecord,
            SeriesProfileRecord.slug == slug,
            _series_profile_from_record,
        )


class SqlAlchemyTeiHeaderRepository(_RepositoryBase, TeiHeaderRepository):
    """Persist TEI headers using SQLAlchemy."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, header: TeiHeader) -> None:
        """Add a TEI header record.

        Parameters
        ----------
        header : TeiHeader
            Parsed TEI header to persist.

        """
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
        """Fetch a TEI header by identifier.

        Parameters
        ----------
        header_id : uuid.UUID
            Identifier of the TEI header to fetch.

        Returns
        -------
        TeiHeader | None
            The matched TEI header, or ``None`` if no match exists.
        """
        return await self._get_one_or_none(
            TeiHeaderRecord,
            TeiHeaderRecord.id == header_id,
            _tei_header_from_record,
        )


class SqlAlchemyEpisodeRepository(_RepositoryBase, EpisodeRepository):
    """Persist canonical episodes using SQLAlchemy."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, episode: CanonicalEpisode) -> None:
        """Add a canonical episode record.

        Parameters
        ----------
        episode : CanonicalEpisode
            Canonical episode domain entity to persist.

        """
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
        """Fetch a canonical episode by identifier.

        Parameters
        ----------
        episode_id : uuid.UUID
            Identifier of the episode to fetch.

        Returns
        -------
        CanonicalEpisode | None
            The matched canonical episode, or ``None`` if no match exists.
        """
        return await self._get_one_or_none(
            EpisodeRecord,
            EpisodeRecord.id == episode_id,
            _episode_from_record,
        )


class SqlAlchemyIngestionJobRepository(_RepositoryBase, IngestionJobRepository):
    """Persist ingestion jobs using SQLAlchemy."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, job: IngestionJob) -> None:
        """Add an ingestion job record.

        Parameters
        ----------
        job : IngestionJob
            Ingestion job domain entity to persist.

        """
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
        """Fetch an ingestion job by identifier.

        Parameters
        ----------
        job_id : uuid.UUID
            Identifier of the ingestion job to fetch.

        Returns
        -------
        IngestionJob | None
            The matched ingestion job, or ``None`` if no match exists.
        """
        return await self._get_one_or_none(
            IngestionJobRecord,
            IngestionJobRecord.id == job_id,
            _ingestion_job_from_record,
        )


class SqlAlchemySourceDocumentRepository(_RepositoryBase, SourceDocumentRepository):
    """Persist source documents using SQLAlchemy."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, document: SourceDocument) -> None:
        """Add a source document record.

        Parameters
        ----------
        document : SourceDocument
            Source document domain entity to persist.

        """
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
        """List source documents for an ingestion job.

        Parameters
        ----------
        job_id : uuid.UUID
            Identifier of the ingestion job to list documents for.

        Returns
        -------
        list[SourceDocument]
            Source documents associated with the ingestion job.
        """
        result = await self._session.execute(
            sa.select(SourceDocumentRecord).where(
                SourceDocumentRecord.ingestion_job_id == job_id
            )
        )
        return [_source_document_from_record(row) for row in result.scalars()]


class SqlAlchemyApprovalEventRepository(_RepositoryBase, ApprovalEventRepository):
    """Persist approval events using SQLAlchemy."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, event: ApprovalEvent) -> None:
        """Add an approval event record.

        Parameters
        ----------
        event : ApprovalEvent
            Approval event domain entity to persist.

        """
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
        """List approval events for a canonical episode.

        Parameters
        ----------
        episode_id : uuid.UUID
            Identifier of the canonical episode.

        Returns
        -------
        list[ApprovalEvent]
            Approval events associated with the episode.
        """
        result = await self._session.execute(
            sa.select(ApprovalEventRecord).where(
                ApprovalEventRecord.episode_id == episode_id
            )
        )
        return [_approval_event_from_record(row) for row in result.scalars()]
