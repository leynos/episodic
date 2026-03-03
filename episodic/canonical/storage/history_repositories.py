"""History-focused SQLAlchemy repositories for canonical persistence."""

import dataclasses as dc
import typing as typ

import sqlalchemy as sa

from episodic.canonical.domain import (
    EpisodeTemplateHistoryEntry,
    SeriesProfileHistoryEntry,
)
from episodic.canonical.ports import (
    EpisodeTemplateHistoryRepository,
    SeriesProfileHistoryRepository,
)

from .mappers import (
    _episode_template_history_from_record,
    _episode_template_history_to_record,
    _series_profile_history_from_record,
    _series_profile_history_to_record,
)
from .models import EpisodeTemplateHistoryRecord, SeriesProfileHistoryRecord
from .repository_base import _RepositoryBase

if typ.TYPE_CHECKING:
    import collections.abc as cabc
    import uuid

    from sqlalchemy.ext.asyncio import AsyncSession
    from sqlalchemy.orm.attributes import InstrumentedAttribute


@dc.dataclass(frozen=True, slots=True)
class HistoryRepositoryConfig[HistoryEntryT, HistoryRecordT]:
    """Configuration for a history repository."""

    record_type: type[HistoryRecordT]
    parent_id_field: str
    mapper: typ.Callable[[HistoryRecordT], HistoryEntryT]
    record_builder: typ.Callable[[HistoryEntryT], HistoryRecordT]


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

    def _get_parent_field(self) -> InstrumentedAttribute[object]:
        """Retrieve the parent ID field from the record type."""
        return getattr(self._record_type, self._parent_id_field)

    def _get_revision_field(self) -> InstrumentedAttribute[object]:
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


class SqlAlchemySeriesProfileHistoryRepository(
    _HistoryRepositoryBase[SeriesProfileHistoryEntry, SeriesProfileHistoryRecord],
    SeriesProfileHistoryRepository,
):
    """Persist series profile history entries using SQLAlchemy."""

    _config: typ.ClassVar[
        HistoryRepositoryConfig[
            SeriesProfileHistoryEntry,
            SeriesProfileHistoryRecord,
        ]
    ] = HistoryRepositoryConfig(
        record_type=SeriesProfileHistoryRecord,
        parent_id_field="series_profile_id",
        mapper=_series_profile_history_from_record,
        record_builder=_series_profile_history_to_record,
    )

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session=session, config=self._config)

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

    _config: typ.ClassVar[
        HistoryRepositoryConfig[
            EpisodeTemplateHistoryEntry,
            EpisodeTemplateHistoryRecord,
        ]
    ] = HistoryRepositoryConfig(
        record_type=EpisodeTemplateHistoryRecord,
        parent_id_field="episode_template_id",
        mapper=_episode_template_history_from_record,
        record_builder=_episode_template_history_to_record,
    )

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session=session, config=self._config)

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


__all__ = (
    "SqlAlchemyEpisodeTemplateHistoryRepository",
    "SqlAlchemySeriesProfileHistoryRepository",
)
