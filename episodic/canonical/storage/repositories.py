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

from episodic.canonical.entity_protocols import (
    ApprovalEventRepository,
    EpisodeTemplateRepository,
    SeriesProfileRepository,
    SourceDocumentProjectionResult,
    SourceDocumentRepository,
    TeiHeaderRepository,
)

from .entity_mappers import (
    _approval_event_from_record,
    _approval_event_to_record,
    _episode_template_from_record,
    _episode_template_to_record,
    _series_profile_from_record,
    _series_profile_to_record,
    _source_document_from_record,
    _source_document_to_record,
    _tei_header_from_record,
    _tei_header_to_record,
)
from .entity_models import (
    ApprovalEventRecord,
    SourceDocumentRecord,
    TeiHeaderRecord,
)
from .history_repositories import (
    SqlAlchemyEpisodeTemplateHistoryRepository,
    SqlAlchemySeriesProfileHistoryRepository,
)
from .integrity_helpers import (
    insert_with_conflict_translation,
    is_source_document_duplicate_integrity_error,
)
from .profile_models import EpisodeTemplateRecord, SeriesProfileRecord
from .reference_repositories import (
    SqlAlchemyReferenceBindingRepository,
    SqlAlchemyReferenceDocumentRepository,
    SqlAlchemyReferenceDocumentRevisionRepository,
)
from .repository_base import _RepositoryBase

if typ.TYPE_CHECKING:
    import collections.abc as cabc
    import uuid

    from sqlalchemy.exc import IntegrityError

    from episodic.canonical.domain import (
        ApprovalEvent,
        EpisodeTemplate,
        SeriesProfile,
        SourceDocument,
        TeiHeader,
    )


class _DuplicateProjectionError(Exception):
    """Signal a recognised source-document projection write race."""


class SqlAlchemySeriesProfileRepository(_RepositoryBase, SeriesProfileRepository):
    """Persist series profiles using SQLAlchemy."""

    async def add(self, profile: SeriesProfile) -> None:
        """Add a series profile record.

        Parameters
        ----------
        profile : SeriesProfile
            Series profile domain entity to persist.

        """
        self._session.add(_series_profile_to_record(profile))

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

    async def list(
        self,
        *,
        limit: int | None = None,
        offset: int = 0,
    ) -> cabc.Sequence[SeriesProfile]:
        """List all series profiles."""
        statement = (
            sa
            .select(SeriesProfileRecord)
            .where(sa.true())
            .order_by(SeriesProfileRecord.created_at, SeriesProfileRecord.id)
            .offset(offset)
        )
        if limit is not None:
            statement = statement.limit(limit)
        result = await self._session.execute(statement)
        return [_series_profile_from_record(row) for row in result.scalars()]

    async def count(self) -> int:
        """Count all series profiles."""
        result = await self._session.execute(
            sa.select(sa.func.count()).select_from(SeriesProfileRecord)
        )
        return result.scalar_one()

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
        self._session.add(_tei_header_to_record(header))

    async def get(self, header_id: uuid.UUID) -> TeiHeader | None:
        """Fetch a TEI header by identifier."""
        return await self._get_one_or_none(
            TeiHeaderRecord,
            TeiHeaderRecord.id == header_id,
            _tei_header_from_record,
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
        self._session.add(_source_document_to_record(document))

    async def add_projection(
        self,
        document: SourceDocument,
    ) -> SourceDocumentProjectionResult:
        """Insert one projection in a savepoint and report a duplicate ID race.

        Parameters
        ----------
        document : SourceDocument
            Deterministically identified source document to persist.

        Returns
        -------
        SourceDocumentProjectionResult
            ``ADDED`` after insertion or ``DUPLICATE`` when a concurrent
            projection with the same deterministic identifier already exists.

        Notes
        -----
        Unrecognised ``IntegrityError`` failures propagate unchanged.
        """

        def _translate(error: IntegrityError) -> BaseException | None:
            if is_source_document_duplicate_integrity_error(error):
                return _DuplicateProjectionError()
            return None

        try:
            await insert_with_conflict_translation(
                self._session,
                _source_document_to_record(document),
                translate=_translate,
            )
        except _DuplicateProjectionError:
            return SourceDocumentProjectionResult.DUPLICATE
        return SourceDocumentProjectionResult.ADDED

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
        self._session.add(_approval_event_to_record(event))

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
        self._session.add(_episode_template_to_record(template))

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
        *,
        limit: int | None = None,
        offset: int = 0,
    ) -> cabc.Sequence[EpisodeTemplate]:
        """List episode templates, optionally by series profile."""
        where_clause: typ.Any = sa.true()
        if series_profile_id is not None:
            where_clause = EpisodeTemplateRecord.series_profile_id == series_profile_id
        statement = (
            sa
            .select(EpisodeTemplateRecord)
            .where(where_clause)
            .order_by(EpisodeTemplateRecord.created_at, EpisodeTemplateRecord.id)
            .offset(offset)
        )
        if limit is not None:
            statement = statement.limit(limit)
        result = await self._session.execute(statement)
        return [_episode_template_from_record(row) for row in result.scalars()]

    async def count(self, series_profile_id: uuid.UUID | None) -> int:
        """Count episode templates, optionally by series profile."""
        where_clause: typ.Any = sa.true()
        if series_profile_id is not None:
            where_clause = EpisodeTemplateRecord.series_profile_id == series_profile_id
        result = await self._session.execute(
            sa
            .select(sa.func.count())
            .select_from(EpisodeTemplateRecord)
            .where(where_clause)
        )
        return result.scalar_one()

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
    "SqlAlchemyEpisodeTemplateHistoryRepository",
    "SqlAlchemyEpisodeTemplateRepository",
    "SqlAlchemyReferenceBindingRepository",
    "SqlAlchemyReferenceDocumentRepository",
    "SqlAlchemyReferenceDocumentRevisionRepository",
    "SqlAlchemySeriesProfileHistoryRepository",
    "SqlAlchemySeriesProfileRepository",
    "SqlAlchemySourceDocumentRepository",
    "SqlAlchemyTeiHeaderRepository",
)
