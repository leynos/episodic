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

import typing as typ

import sqlalchemy as sa

from episodic.canonical.ports import (
    ApprovalEventRepository,
    EpisodeRepository,
    EpisodeTemplateRepository,
    IngestionJobRepository,
    SeriesProfileRepository,
    SourceDocumentRepository,
    TeiHeaderRepository,
)

from .history_repositories import (
    SqlAlchemyEpisodeTemplateHistoryRepository,
    SqlAlchemySeriesProfileHistoryRepository,
)
from .mappers import (
    _approval_event_from_record,
    _approval_event_to_record,
    _episode_from_record,
    _episode_template_from_record,
    _episode_template_to_record,
    _episode_to_record,
    _ingestion_job_from_record,
    _ingestion_job_to_record,
    _series_profile_from_record,
    _series_profile_to_record,
    _source_document_from_record,
    _source_document_to_record,
    _tei_header_from_record,
    _tei_header_to_record,
)
from .models import (
    ApprovalEventRecord,
    EpisodeRecord,
    EpisodeTemplateRecord,
    IngestionJobRecord,
    SeriesProfileRecord,
    SourceDocumentRecord,
    TeiHeaderRecord,
)
from .reference_repositories import (
    SqlAlchemyReferenceBindingRepository,
    SqlAlchemyReferenceDocumentRepository,
    SqlAlchemyReferenceDocumentRevisionRepository,
)
from .repository_base import _RepositoryBase

if typ.TYPE_CHECKING:
    import uuid

    from episodic.canonical.domain import (
        ApprovalEvent,
        CanonicalEpisode,
        EpisodeTemplate,
        IngestionJob,
        SeriesProfile,
        SourceDocument,
        TeiHeader,
    )


class SqlAlchemySeriesProfileRepository(_RepositoryBase, SeriesProfileRepository):
    """Persist series profiles using SQLAlchemy."""

    async def add(self, profile: SeriesProfile) -> None:
        """Add a series profile record.

        Parameters
        ----------
        profile : SeriesProfile
            Series profile domain entity to persist.

        """
        await self._add_record(_series_profile_to_record(profile))

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
        return await self._list_where(
            SeriesProfileRecord,
            sa.true(),
            SeriesProfileRecord.created_at,
            _series_profile_from_record,
        )

    async def update(self, profile: SeriesProfile) -> None:
        """Persist changes to an existing series profile."""
        await self._update_entity_fields(
            SeriesProfileRecord,
            profile,
            [
                "slug",
                "title",
                "description",
                "configuration",
                "guardrails",
                "updated_at",
            ],
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
        await self._add_record(_tei_header_to_record(header))

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
        await self._add_record(_episode_to_record(episode))

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
        await self._add_record(_ingestion_job_to_record(job))

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
        await self._add_record(_source_document_to_record(document))

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
        return await self._list_where(
            SourceDocumentRecord,
            SourceDocumentRecord.ingestion_job_id == job_id,
            SourceDocumentRecord.created_at,
            _source_document_from_record,
        )


class SqlAlchemyApprovalEventRepository(_RepositoryBase, ApprovalEventRepository):
    """Persist approval events using SQLAlchemy."""

    async def add(self, event: ApprovalEvent) -> None:
        """Add an approval event record.

        Parameters
        ----------
        event : ApprovalEvent
            Approval event domain entity to persist.

        """
        await self._add_record(_approval_event_to_record(event))

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
        return await self._list_where(
            ApprovalEventRecord,
            ApprovalEventRecord.episode_id == episode_id,
            ApprovalEventRecord.created_at,
            _approval_event_from_record,
        )


class SqlAlchemyEpisodeTemplateRepository(_RepositoryBase, EpisodeTemplateRepository):
    """Persist episode templates using SQLAlchemy."""

    async def add(self, template: EpisodeTemplate) -> None:
        """Add an episode template record."""
        await self._add_record(_episode_template_to_record(template))

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
        where_clause: typ.Any = sa.true()
        if series_profile_id is not None:
            where_clause = EpisodeTemplateRecord.series_profile_id == series_profile_id
        return await self._list_where(
            EpisodeTemplateRecord,
            where_clause,
            EpisodeTemplateRecord.created_at,
            _episode_template_from_record,
        )

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
        await self._update_entity_fields(
            EpisodeTemplateRecord,
            template,
            ["slug", "title", "description", "structure", "guardrails", "updated_at"],
        )


__all__ = (
    "SqlAlchemyApprovalEventRepository",
    "SqlAlchemyEpisodeRepository",
    "SqlAlchemyEpisodeTemplateHistoryRepository",
    "SqlAlchemyEpisodeTemplateRepository",
    "SqlAlchemyIngestionJobRepository",
    "SqlAlchemyReferenceBindingRepository",
    "SqlAlchemyReferenceDocumentRepository",
    "SqlAlchemyReferenceDocumentRevisionRepository",
    "SqlAlchemySeriesProfileHistoryRepository",
    "SqlAlchemySeriesProfileRepository",
    "SqlAlchemySourceDocumentRepository",
    "SqlAlchemyTeiHeaderRepository",
)
