"""Repository protocols for canonical revision history."""

import typing as typ

if typ.TYPE_CHECKING:
    import collections.abc as cabc
    import uuid

    from .domain import EpisodeTemplateHistoryEntry, SeriesProfileHistoryEntry


class SeriesProfileHistoryRepository(typ.Protocol):
    """Persistence interface for series profile history entries."""

    async def add(self, entry: SeriesProfileHistoryEntry) -> None:
        """Persist a profile history entry."""
        raise NotImplementedError

    async def list_for_profile(
        self,
        profile_id: uuid.UUID,
    ) -> list[SeriesProfileHistoryEntry]:
        """List history entries for a series profile."""
        raise NotImplementedError

    async def list_for_profile_paged(
        self,
        profile_id: uuid.UUID,
        *,
        limit: int,
        offset: int,
    ) -> list[SeriesProfileHistoryEntry]:
        """List paged history entries for a series profile."""
        raise NotImplementedError

    async def count_for_profile(self, profile_id: uuid.UUID) -> int:
        """Count history entries for a series profile."""
        raise NotImplementedError

    async def get_latest_for_profile(
        self,
        profile_id: uuid.UUID,
    ) -> SeriesProfileHistoryEntry | None:
        """Fetch the most recent history entry for a series profile."""
        raise NotImplementedError

    async def get_latest_revisions_for_profiles(
        self,
        profile_ids: cabc.Collection[uuid.UUID],
    ) -> dict[uuid.UUID, int]:
        """Fetch latest revisions for a set of series profiles."""
        raise NotImplementedError


class EpisodeTemplateHistoryRepository(typ.Protocol):
    """Persistence interface for episode template history entries."""

    async def add(self, entry: EpisodeTemplateHistoryEntry) -> None:
        """Persist an episode template history entry."""
        raise NotImplementedError

    async def list_for_template(
        self,
        template_id: uuid.UUID,
    ) -> list[EpisodeTemplateHistoryEntry]:
        """List history entries for an episode template."""
        raise NotImplementedError

    async def list_for_template_paged(
        self,
        template_id: uuid.UUID,
        *,
        limit: int,
        offset: int,
    ) -> list[EpisodeTemplateHistoryEntry]:
        """List paged history entries for an episode template."""
        raise NotImplementedError

    async def count_for_template(self, template_id: uuid.UUID) -> int:
        """Count history entries for an episode template."""
        raise NotImplementedError

    async def get_latest_for_template(
        self,
        template_id: uuid.UUID,
    ) -> EpisodeTemplateHistoryEntry | None:
        """Fetch the most recent history entry for an episode template."""
        raise NotImplementedError

    async def get_latest_revisions_for_templates(
        self,
        template_ids: cabc.Collection[uuid.UUID],
    ) -> dict[uuid.UUID, int]:
        """Fetch latest revisions for a set of episode templates."""
        raise NotImplementedError
