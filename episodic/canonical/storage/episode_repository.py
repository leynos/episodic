"""SQLAlchemy repository for canonical episodes."""

import datetime as dt
import typing as typ

import sqlalchemy as sa

from episodic.canonical.entity_protocols import EpisodeRepository
from episodic.canonical.episode_errors import EpisodeNotFound, EpisodeRevisionConflict

from .compression import encode_text_for_storage
from .entity_mappers import _episode_from_record, _episode_to_record, _tei_content_hash
from .entity_models import EpisodeRecord
from .repository_base import _RepositoryBase

if typ.TYPE_CHECKING:
    import collections.abc as cabc
    import uuid

    from sqlalchemy.engine import CursorResult

    from episodic.canonical.domain import CanonicalEpisode, EpisodeTeiUpdate


def _utc_now() -> dt.datetime:
    """Return a timezone-aware UTC timestamp for repository updates."""
    return dt.datetime.now(dt.UTC)


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

    async def list_by_ids(
        self, episode_ids: cabc.Collection[uuid.UUID]
    ) -> list[CanonicalEpisode]:
        """Fetch canonical episodes by identifiers."""
        if not episode_ids:
            return []

        return await self._get_many(
            EpisodeRecord,
            EpisodeRecord.id.in_(episode_ids),
            _episode_from_record,
        )

    async def update(
        self,
        episode_id: uuid.UUID,
        *,
        update: EpisodeTeiUpdate,
    ) -> CanonicalEpisode:
        """Update episode TEI when the expected revision still matches."""
        stored_tei_xml, tei_xml_zstd = encode_text_for_storage(update.tei_xml)
        now = update.updated_at or _utc_now()
        result = await self._session.execute(
            sa
            .update(EpisodeRecord)
            .where(
                EpisodeRecord.id == episode_id,
                EpisodeRecord.tei_revision == update.expected_revision,
            )
            .values(
                tei_xml=stored_tei_xml,
                tei_xml_zstd=tei_xml_zstd,
                tei_revision=update.expected_revision + 1,
                tei_content_hash=_tei_content_hash(update.tei_xml),
                qa_status=update.qa_status,
                last_generation_run_id=update.last_generation_run_id,
                updated_at=now,
            )
        )
        cursor_result = typ.cast("CursorResult[typ.Any]", result)
        if cursor_result.rowcount != 1:
            existing = await self.get(episode_id)
            if existing is None:
                raise EpisodeNotFound(episode_id)
            raise EpisodeRevisionConflict(episode_id, update.expected_revision)

        await self._session.flush()
        updated = await self.get(episode_id)
        if updated is None:  # pragma: no cover - guarded by updated row.
            raise EpisodeNotFound(episode_id)
        return updated
