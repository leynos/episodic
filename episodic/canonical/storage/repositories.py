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

import dataclasses as dc
import typing as typ

import sqlalchemy as sa

from episodic.canonical.domain import (
    EpisodeTemplateHistoryEntry,
    ReferenceBinding,
    ReferenceBindingTargetKind,
    ReferenceDocument,
    ReferenceDocumentRevision,
    SeriesProfileHistoryEntry,
)
from episodic.canonical.ports import (
    ApprovalEventRepository,
    EpisodeRepository,
    EpisodeTemplateHistoryRepository,
    EpisodeTemplateRepository,
    IngestionJobRepository,
    ReferenceBindingRepository,
    ReferenceDocumentRepository,
    ReferenceDocumentRevisionRepository,
    SeriesProfileHistoryRepository,
    SeriesProfileRepository,
    SourceDocumentRepository,
    TeiHeaderRepository,
)

from .mappers import (
    _approval_event_from_record,
    _approval_event_to_record,
    _episode_from_record,
    _episode_template_from_record,
    _episode_template_history_from_record,
    _episode_template_history_to_record,
    _episode_template_to_record,
    _episode_to_record,
    _ingestion_job_from_record,
    _ingestion_job_to_record,
    _reference_binding_from_record,
    _reference_binding_to_record,
    _reference_document_from_record,
    _reference_document_revision_from_record,
    _reference_document_revision_to_record,
    _reference_document_to_record,
    _series_profile_from_record,
    _series_profile_history_from_record,
    _series_profile_history_to_record,
    _series_profile_to_record,
    _source_document_from_record,
    _source_document_to_record,
    _tei_header_from_record,
    _tei_header_to_record,
)
from .models import (
    ApprovalEventRecord,
    EpisodeRecord,
    EpisodeTemplateHistoryRecord,
    EpisodeTemplateRecord,
    IngestionJobRecord,
    ReferenceBindingRecord,
    ReferenceDocumentRecord,
    ReferenceDocumentRevisionRecord,
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
        IngestionJob,
        SeriesProfile,
        SourceDocument,
        TeiHeader,
    )


@dc.dataclass(frozen=True, slots=True)
class HistoryRepositoryConfig[HistoryEntryT, HistoryRecordT]:
    """Configuration for a history repository."""

    record_type: type[HistoryRecordT]
    parent_id_field: str
    mapper: typ.Callable[[HistoryRecordT], HistoryEntryT]
    record_builder: typ.Callable[[HistoryEntryT], HistoryRecordT]


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

    async def _add_record[RecordT](self, record: RecordT) -> None:
        """Add a record to the current SQLAlchemy session."""
        self._session.add(record)

    async def _list_where[RecordT, DomainT](
        self,
        record_type: type[RecordT],
        where_clause: typ.Any,  # noqa: ANN401  # TODO(@codex): https://github.com/leynos/episodic/pull/14 - SQLAlchemy clause typing.
        order_by_clause: typ.Any,  # noqa: ANN401  # TODO(@codex): https://github.com/leynos/episodic/pull/14 - SQLAlchemy clause typing.
        mapper: cabc.Callable[[RecordT], DomainT],
    ) -> list[DomainT]:
        """List mapped records matching a filter and ordering."""
        result = await self._session.execute(
            sa.select(record_type).where(where_clause).order_by(order_by_clause)
        )
        return [mapper(row) for row in result.scalars()]

    async def _get_latest_where[RecordT, DomainT](
        self,
        record_type: type[RecordT],
        where_clause: typ.Any,  # noqa: ANN401  # TODO(@codex): https://github.com/leynos/episodic/pull/14 - SQLAlchemy clause typing.
        order_by_desc_clause: typ.Any,  # noqa: ANN401  # TODO(@codex): https://github.com/leynos/episodic/pull/14 - SQLAlchemy clause typing.
        mapper: cabc.Callable[[RecordT], DomainT],
    ) -> DomainT | None:
        """Return the latest mapped record matching a filter."""
        result = await self._session.execute(
            sa
            .select(record_type)
            .where(where_clause)
            .order_by(order_by_desc_clause)
            .limit(1)
        )
        record = result.scalar_one_or_none()
        if record is None:
            return None
        return mapper(record)

    async def _update_where(
        self,
        record_type: type[object],
        where_clause: typ.Any,  # noqa: ANN401  # TODO(@codex): https://github.com/leynos/episodic/pull/14 - SQLAlchemy clause typing.
        values: dict[str, typ.Any],
    ) -> None:
        """Execute an update statement for matching records."""
        await self._session.execute(
            sa.update(record_type).where(where_clause).values(**values)
        )

    async def _update_entity_fields[EntityT](
        self,
        record_type: type[object],
        entity: EntityT,
        field_names: cabc.Sequence[str],
    ) -> None:
        """Update entity fields using the entity's current attribute values."""
        values = {field: getattr(entity, field) for field in field_names}
        id_field_name = "id"
        entity_id = getattr(entity, id_field_name)
        id_field = getattr(record_type, id_field_name)
        await self._update_where(record_type, id_field == entity_id, values)


class _HistoryRepositoryBase[HistoryEntryT, HistoryRecordT](_RepositoryBase):
    """Shared implementation for history repositories."""

    def __init__(
        self,
        session: AsyncSession,
        config: HistoryRepositoryConfig[HistoryEntryT, HistoryRecordT],
    ) -> None:
        super().__init__(session)
        self._record_type = config.record_type
        self._parent_id_field = config.parent_id_field
        self._mapper = config.mapper
        self._record_builder = config.record_builder

    def _get_parent_field(self) -> typ.Any:  # noqa: ANN401
        """Retrieve the parent ID field from the record type."""
        return getattr(self._record_type, self._parent_id_field)

    def _get_revision_field(self) -> typ.Any:  # noqa: ANN401
        """Retrieve the revision field from the record type."""
        revision_field_name = "revision"
        return getattr(self._record_type, revision_field_name)

    async def _add_history_entry(self, entry: HistoryEntryT) -> None:
        """Persist a history entry record."""
        await self._add_record(self._record_builder(entry))

    async def _list_for_parent(self, parent_id: uuid.UUID) -> list[HistoryEntryT]:
        """List history entries for a parent entity."""
        return await self._list_where(
            self._record_type,
            self._get_parent_field() == parent_id,
            self._get_revision_field(),
            self._mapper,
        )

    async def _get_latest_for_parent(
        self,
        parent_id: uuid.UUID,
    ) -> HistoryEntryT | None:
        """Fetch the latest history entry for a parent entity."""
        return await self._get_latest_where(
            self._record_type,
            self._get_parent_field() == parent_id,
            self._get_revision_field().desc(),
            self._mapper,
        )

    async def _get_latest_revisions_for_parents(
        self,
        parent_ids: cabc.Collection[uuid.UUID],
    ) -> dict[uuid.UUID, int]:
        """Fetch latest revision values for parent entity identifiers."""
        if not parent_ids:
            return {}

        parent_field = self._get_parent_field()
        revision_field = self._get_revision_field()
        latest_revisions = (
            sa
            .select(
                parent_field.label("parent_id"),
                sa.func.max(revision_field).label("revision"),
            )
            .where(parent_field.in_(list(parent_ids)))
            .group_by(parent_field)
            .subquery()
        )
        result = await self._session.execute(
            sa.select(
                latest_revisions.c.parent_id,
                latest_revisions.c.revision,
            )
        )
        return {row.parent_id: int(row.revision) for row in result}


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
            ["slug", "title", "description", "configuration", "updated_at"],
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


class SqlAlchemyReferenceDocumentRepository(
    _RepositoryBase, ReferenceDocumentRepository
):
    """Persist reusable reference documents using SQLAlchemy."""

    async def add(self, document: ReferenceDocument) -> None:
        """Add a reusable reference document record."""
        await self._add_record(_reference_document_to_record(document))

    async def get(self, document_id: uuid.UUID) -> ReferenceDocument | None:
        """Fetch a reusable reference document by identifier."""
        return await self._get_one_or_none(
            ReferenceDocumentRecord,
            ReferenceDocumentRecord.id == document_id,
            _reference_document_from_record,
        )

    async def list_for_series(
        self,
        series_profile_id: uuid.UUID,
    ) -> list[ReferenceDocument]:
        """List reusable reference documents for one series profile."""
        return await self._list_where(
            ReferenceDocumentRecord,
            ReferenceDocumentRecord.owner_series_profile_id == series_profile_id,
            ReferenceDocumentRecord.created_at,
            _reference_document_from_record,
        )

    async def update(self, document: ReferenceDocument) -> None:
        """Persist changes to an existing reusable reference document."""
        await self._update_where(
            ReferenceDocumentRecord,
            ReferenceDocumentRecord.id == document.id,
            {
                "owner_series_profile_id": document.owner_series_profile_id,
                "kind": document.kind,
                "lifecycle_state": document.lifecycle_state,
                "metadata_payload": document.metadata,
                "updated_at": document.updated_at,
            },
        )


class SqlAlchemyReferenceDocumentRevisionRepository(
    _RepositoryBase, ReferenceDocumentRevisionRepository
):
    """Persist reusable reference document revisions using SQLAlchemy."""

    async def add(self, revision: ReferenceDocumentRevision) -> None:
        """Add an immutable reusable reference revision record."""
        await self._add_record(_reference_document_revision_to_record(revision))

    async def get(self, revision_id: uuid.UUID) -> ReferenceDocumentRevision | None:
        """Fetch a reusable reference revision by identifier."""
        return await self._get_one_or_none(
            ReferenceDocumentRevisionRecord,
            ReferenceDocumentRevisionRecord.id == revision_id,
            _reference_document_revision_from_record,
        )

    async def list_for_document(
        self,
        document_id: uuid.UUID,
    ) -> list[ReferenceDocumentRevision]:
        """List revisions for one reusable reference document."""
        return await self._list_where(
            ReferenceDocumentRevisionRecord,
            ReferenceDocumentRevisionRecord.reference_document_id == document_id,
            ReferenceDocumentRevisionRecord.created_at,
            _reference_document_revision_from_record,
        )

    async def get_latest_for_document(
        self,
        document_id: uuid.UUID,
    ) -> ReferenceDocumentRevision | None:
        """Fetch the latest revision for one reusable reference document."""
        return await self._get_latest_where(
            ReferenceDocumentRevisionRecord,
            ReferenceDocumentRevisionRecord.reference_document_id == document_id,
            ReferenceDocumentRevisionRecord.created_at.desc(),
            _reference_document_revision_from_record,
        )


class SqlAlchemyReferenceBindingRepository(_RepositoryBase, ReferenceBindingRepository):
    """Persist reusable reference bindings using SQLAlchemy."""

    @staticmethod
    def _target_field(target_kind: ReferenceBindingTargetKind) -> typ.Any:  # noqa: ANN401
        """Resolve the SQLAlchemy target column for a binding target kind."""
        match target_kind:
            case ReferenceBindingTargetKind.SERIES_PROFILE:
                return ReferenceBindingRecord.series_profile_id
            case ReferenceBindingTargetKind.EPISODE_TEMPLATE:
                return ReferenceBindingRecord.episode_template_id
            case ReferenceBindingTargetKind.INGESTION_JOB:
                return ReferenceBindingRecord.ingestion_job_id
            case _:
                msg = f"Unsupported reference binding target kind: {target_kind}"
                raise ValueError(msg)

    async def add(self, binding: ReferenceBinding) -> None:
        """Add a reusable reference binding record."""
        await self._add_record(_reference_binding_to_record(binding))

    async def list_for_target(
        self,
        *,
        target_kind: ReferenceBindingTargetKind,
        target_id: uuid.UUID,
    ) -> list[ReferenceBinding]:
        """List reusable reference bindings for one target context."""
        target_field = self._target_field(target_kind)
        return await self._list_where(
            ReferenceBindingRecord,
            sa.and_(
                ReferenceBindingRecord.target_kind == target_kind,
                target_field == target_id,
            ),
            ReferenceBindingRecord.created_at,
            _reference_binding_from_record,
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
            ["slug", "title", "description", "structure", "updated_at"],
        )


class SqlAlchemySeriesProfileHistoryRepository(
    _HistoryRepositoryBase[SeriesProfileHistoryEntry, SeriesProfileHistoryRecord],
    SeriesProfileHistoryRepository,
):
    """Persist series profile history entries using SQLAlchemy."""

    def __init__(self, session: AsyncSession) -> None:
        config = HistoryRepositoryConfig(
            record_type=SeriesProfileHistoryRecord,
            parent_id_field="series_profile_id",
            mapper=_series_profile_history_from_record,
            record_builder=_series_profile_history_to_record,
        )
        super().__init__(
            session=session,
            config=config,
        )

    async def add(self, entry: SeriesProfileHistoryEntry) -> None:
        """Add a profile history entry."""
        await self._add_history_entry(entry)

    async def list_for_profile(
        self,
        profile_id: uuid.UUID,
    ) -> list[SeriesProfileHistoryEntry]:
        """List history entries for a series profile."""
        return await self._list_for_parent(profile_id)

    async def get_latest_for_profile(
        self,
        profile_id: uuid.UUID,
    ) -> SeriesProfileHistoryEntry | None:
        """Fetch the latest history entry for a series profile."""
        return await self._get_latest_for_parent(profile_id)

    async def get_latest_revisions_for_profiles(
        self,
        profile_ids: cabc.Collection[uuid.UUID],
    ) -> dict[uuid.UUID, int]:
        """Fetch latest revision numbers for series profiles."""
        return await self._get_latest_revisions_for_parents(profile_ids)


class SqlAlchemyEpisodeTemplateHistoryRepository(
    _HistoryRepositoryBase[
        EpisodeTemplateHistoryEntry,
        EpisodeTemplateHistoryRecord,
    ],
    EpisodeTemplateHistoryRepository,
):
    """Persist episode template history entries using SQLAlchemy."""

    def __init__(self, session: AsyncSession) -> None:
        config = HistoryRepositoryConfig(
            record_type=EpisodeTemplateHistoryRecord,
            parent_id_field="episode_template_id",
            mapper=_episode_template_history_from_record,
            record_builder=_episode_template_history_to_record,
        )
        super().__init__(
            session=session,
            config=config,
        )

    async def add(self, entry: EpisodeTemplateHistoryEntry) -> None:
        """Add a template history entry."""
        await self._add_history_entry(entry)

    async def list_for_template(
        self,
        template_id: uuid.UUID,
    ) -> list[EpisodeTemplateHistoryEntry]:
        """List history entries for an episode template."""
        return await self._list_for_parent(template_id)

    async def get_latest_for_template(
        self,
        template_id: uuid.UUID,
    ) -> EpisodeTemplateHistoryEntry | None:
        """Fetch the latest history entry for an episode template."""
        return await self._get_latest_for_parent(template_id)

    async def get_latest_revisions_for_templates(
        self,
        template_ids: cabc.Collection[uuid.UUID],
    ) -> dict[uuid.UUID, int]:
        """Fetch latest revision numbers for episode templates."""
        return await self._get_latest_revisions_for_parents(template_ids)
