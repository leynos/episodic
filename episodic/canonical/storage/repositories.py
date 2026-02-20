"""SQLAlchemy repositories for canonical content.

This module implements repository adapters that translate domain entities to
SQLAlchemy ORM records. Repositories operate within a supplied async session
and are intended to be composed through the canonical unit-of-work.

Examples
--------
Create a repository with the unit-of-work session:

>>> async with SqlAlchemyUnitOfWork(session_factory) as uow:
...     repo = uow.series_profiles
...     await repo.add(profile)
...     await uow.commit()
"""

from __future__ import annotations

import dataclasses as dc
import typing as typ

import sqlalchemy as sa

from episodic.canonical.ports import (
    ApprovalEventRepository,
    EpisodeRepository,
    EpisodeTemplateHistoryRepository,
    EpisodeTemplateRepository,
    IngestionJobRepository,
    SeriesProfileHistoryRepository,
    SeriesProfileRepository,
    SourceDocumentRepository,
    TeiHeaderRepository,
)

from .mappers import (
    _approval_event_from_record,
    _episode_from_record,
    _episode_template_from_record,
    _episode_template_history_from_record,
    _ingestion_job_from_record,
    _series_profile_from_record,
    _series_profile_history_from_record,
    _source_document_from_record,
    _tei_header_from_record,
)
from .models import (
    ApprovalEventRecord,
    EpisodeRecord,
    EpisodeTemplateHistoryRecord,
    EpisodeTemplateRecord,
    IngestionJobRecord,
    SeriesProfileHistoryRecord,
    SeriesProfileRecord,
    SourceDocumentRecord,
    TeiHeaderRecord,
)

if typ.TYPE_CHECKING:
    import collections.abc as cabc
    import uuid

    from sqlalchemy.ext.asyncio import AsyncSession

    from episodic.canonical.domain import (
        ApprovalEvent,
        CanonicalEpisode,
        EpisodeTemplate,
        EpisodeTemplateHistoryEntry,
        IngestionJob,
        SeriesProfile,
        SeriesProfileHistoryEntry,
        SourceDocument,
        TeiHeader,
    )


@dc.dataclass(slots=True)
class _RepositoryBase:
    """Shared helpers for SQLAlchemy repositories."""

    _session: AsyncSession

    async def _get_one_or_none[RecordT, DomainT](
        self,
        record_type: type[RecordT],
        where_clause: typ.Any,  # noqa: ANN401  # TODO(@codex): https://github.com/leynos/episodic/pull/14 - SQLAlchemy clause typing.
        mapper: cabc.Callable[[RecordT], DomainT],
    ) -> DomainT | None:
        """Return a mapped record for the query or None."""
        result = await self._session.execute(sa.select(record_type).where(where_clause))
        record = result.scalar_one_or_none()
        if record is None:
            return None
        return mapper(record)


class SqlAlchemySeriesProfileRepository(_RepositoryBase, SeriesProfileRepository):
    """Persist series profiles using SQLAlchemy."""

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
        return  # noqa: PLR1711

    async def get(self, profile_id: uuid.UUID) -> SeriesProfile | None:
        """Fetch a series profile by identifier."""
        return await self._get_one_or_none(
            SeriesProfileRecord,
            SeriesProfileRecord.id == profile_id,
            _series_profile_from_record,
        )

    async def get_by_slug(self, slug: str) -> SeriesProfile | None:
        """Fetch a series profile by slug."""
        return await self._get_one_or_none(
            SeriesProfileRecord,
            SeriesProfileRecord.slug == slug,
            _series_profile_from_record,
        )

    async def list(self) -> typ.Sequence[SeriesProfile]:
        """List all series profiles."""
        result = await self._session.execute(
            sa.select(SeriesProfileRecord).order_by(SeriesProfileRecord.created_at)
        )
        return [_series_profile_from_record(row) for row in result.scalars()]

    async def update(self, profile: SeriesProfile) -> None:
        """Persist changes to an existing series profile."""
        await self._session.execute(
            sa
            .update(SeriesProfileRecord)
            .where(SeriesProfileRecord.id == profile.id)
            .values(
                slug=profile.slug,
                title=profile.title,
                description=profile.description,
                configuration=profile.configuration,
                updated_at=profile.updated_at,
            )
        )


class SqlAlchemyTeiHeaderRepository(_RepositoryBase, TeiHeaderRepository):
    """Persist TEI headers using SQLAlchemy."""

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
        return  # noqa: PLR1711

    async def get(self, header_id: uuid.UUID) -> TeiHeader | None:
        """Fetch a TEI header by identifier."""
        return await self._get_one_or_none(
            TeiHeaderRecord,
            TeiHeaderRecord.id == header_id,
            _tei_header_from_record,
        )


class SqlAlchemyEpisodeRepository(_RepositoryBase, EpisodeRepository):
    """Persist canonical episodes using SQLAlchemy."""

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
        return  # noqa: PLR1711

    async def get(self, episode_id: uuid.UUID) -> CanonicalEpisode | None:
        """Fetch a canonical episode by identifier."""
        return await self._get_one_or_none(
            EpisodeRecord,
            EpisodeRecord.id == episode_id,
            _episode_from_record,
        )


class SqlAlchemyIngestionJobRepository(_RepositoryBase, IngestionJobRepository):
    """Persist ingestion jobs using SQLAlchemy."""

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
        return  # noqa: PLR1711

    async def get(self, job_id: uuid.UUID) -> IngestionJob | None:
        """Fetch an ingestion job by identifier."""
        return await self._get_one_or_none(
            IngestionJobRecord,
            IngestionJobRecord.id == job_id,
            _ingestion_job_from_record,
        )


class SqlAlchemySourceDocumentRepository(_RepositoryBase, SourceDocumentRepository):
    """Persist source documents using SQLAlchemy."""

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
        return  # noqa: PLR1711

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
            sa
            .select(SourceDocumentRecord)
            .where(SourceDocumentRecord.ingestion_job_id == job_id)
            .order_by(SourceDocumentRecord.created_at)
        )
        return [_source_document_from_record(row) for row in result.scalars()]


class SqlAlchemyApprovalEventRepository(_RepositoryBase, ApprovalEventRepository):
    """Persist approval events using SQLAlchemy."""

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
        return  # noqa: PLR1711

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
            sa
            .select(ApprovalEventRecord)
            .where(ApprovalEventRecord.episode_id == episode_id)
            .order_by(ApprovalEventRecord.created_at)
        )
        return [_approval_event_from_record(row) for row in result.scalars()]


class SqlAlchemyEpisodeTemplateRepository(_RepositoryBase, EpisodeTemplateRepository):
    """Persist episode templates using SQLAlchemy."""

    async def add(self, template: EpisodeTemplate) -> None:
        """Add an episode template record."""
        self._session.add(
            EpisodeTemplateRecord(
                id=template.id,
                series_profile_id=template.series_profile_id,
                slug=template.slug,
                title=template.title,
                description=template.description,
                structure=template.structure,
                created_at=template.created_at,
                updated_at=template.updated_at,
            )
        )
        return  # noqa: PLR1711

    async def get(self, template_id: uuid.UUID) -> EpisodeTemplate | None:
        """Fetch an episode template by identifier."""
        return await self._get_one_or_none(
            EpisodeTemplateRecord,
            EpisodeTemplateRecord.id == template_id,
            _episode_template_from_record,
        )

    async def list(
        self,
        series_profile_id: uuid.UUID | None,
    ) -> typ.Sequence[EpisodeTemplate]:
        """List episode templates, optionally by series profile."""
        query = sa.select(EpisodeTemplateRecord)
        if series_profile_id is not None:
            query = query.where(
                EpisodeTemplateRecord.series_profile_id == series_profile_id
            )
        result = await self._session.execute(
            query.order_by(EpisodeTemplateRecord.created_at)
        )
        return [_episode_template_from_record(row) for row in result.scalars()]

    async def get_by_slug(
        self,
        series_profile_id: uuid.UUID,
        slug: str,
    ) -> EpisodeTemplate | None:
        """Fetch an episode template by series profile and slug."""
        return await self._get_one_or_none(
            EpisodeTemplateRecord,
            sa.and_(
                EpisodeTemplateRecord.series_profile_id == series_profile_id,
                EpisodeTemplateRecord.slug == slug,
            ),
            _episode_template_from_record,
        )

    async def update(self, template: EpisodeTemplate) -> None:
        """Persist changes to an existing episode template."""
        await self._session.execute(
            sa
            .update(EpisodeTemplateRecord)
            .where(EpisodeTemplateRecord.id == template.id)
            .values(
                slug=template.slug,
                title=template.title,
                description=template.description,
                structure=template.structure,
                updated_at=template.updated_at,
            )
        )


class SqlAlchemySeriesProfileHistoryRepository(
    _RepositoryBase,
    SeriesProfileHistoryRepository,
):
    """Persist series profile history entries using SQLAlchemy."""

    async def add(self, entry: SeriesProfileHistoryEntry) -> None:
        """Add a profile history entry."""
        self._session.add(
            SeriesProfileHistoryRecord(
                id=entry.id,
                series_profile_id=entry.series_profile_id,
                revision=entry.revision,
                actor=entry.actor,
                note=entry.note,
                snapshot=entry.snapshot,
                created_at=entry.created_at,
            )
        )
        return  # noqa: PLR1711

    async def list_for_profile(
        self,
        profile_id: uuid.UUID,
    ) -> list[SeriesProfileHistoryEntry]:
        """List history entries for a series profile."""
        result = await self._session.execute(
            sa
            .select(SeriesProfileHistoryRecord)
            .where(SeriesProfileHistoryRecord.series_profile_id == profile_id)
            .order_by(SeriesProfileHistoryRecord.revision)
        )
        return [_series_profile_history_from_record(row) for row in result.scalars()]

    async def get_latest_for_profile(
        self,
        profile_id: uuid.UUID,
    ) -> SeriesProfileHistoryEntry | None:
        """Fetch the latest history entry for a series profile."""
        result = await self._session.execute(
            sa
            .select(SeriesProfileHistoryRecord)
            .where(SeriesProfileHistoryRecord.series_profile_id == profile_id)
            .order_by(SeriesProfileHistoryRecord.revision.desc())
            .limit(1)
        )
        record = result.scalar_one_or_none()
        if record is None:
            return None
        return _series_profile_history_from_record(record)


class SqlAlchemyEpisodeTemplateHistoryRepository(
    _RepositoryBase,
    EpisodeTemplateHistoryRepository,
):
    """Persist episode template history entries using SQLAlchemy."""

    async def add(self, entry: EpisodeTemplateHistoryEntry) -> None:
        """Add a template history entry."""
        self._session.add(
            EpisodeTemplateHistoryRecord(
                id=entry.id,
                episode_template_id=entry.episode_template_id,
                revision=entry.revision,
                actor=entry.actor,
                note=entry.note,
                snapshot=entry.snapshot,
                created_at=entry.created_at,
            )
        )
        return  # noqa: PLR1711

    async def list_for_template(
        self,
        template_id: uuid.UUID,
    ) -> list[EpisodeTemplateHistoryEntry]:
        """List history entries for an episode template."""
        result = await self._session.execute(
            sa
            .select(EpisodeTemplateHistoryRecord)
            .where(EpisodeTemplateHistoryRecord.episode_template_id == template_id)
            .order_by(EpisodeTemplateHistoryRecord.revision)
        )
        return [_episode_template_history_from_record(row) for row in result.scalars()]

    async def get_latest_for_template(
        self,
        template_id: uuid.UUID,
    ) -> EpisodeTemplateHistoryEntry | None:
        """Fetch the latest history entry for an episode template."""
        result = await self._session.execute(
            sa
            .select(EpisodeTemplateHistoryRecord)
            .where(EpisodeTemplateHistoryRecord.episode_template_id == template_id)
            .order_by(EpisodeTemplateHistoryRecord.revision.desc())
            .limit(1)
        )
        record = result.scalar_one_or_none()
        if record is None:
            return None
        return _episode_template_history_from_record(record)
