"""Repository protocols for core canonical entities."""

import typing as typ

if typ.TYPE_CHECKING:
    import collections.abc as cabc
    import uuid

    from .domain import (
        ApprovalEvent,
        CanonicalEpisode,
        EpisodeTeiUpdate,
        EpisodeTemplate,
        IngestionJob,
        IngestionJobListFilters,
        IntakeState,
        SeriesProfile,
        SourceDocument,
        TeiHeader,
    )


class SeriesProfileRepository(typ.Protocol):
    """Persistence interface for series profiles."""

    async def add(self, profile: SeriesProfile) -> None:
        """Persist a series profile."""
        raise NotImplementedError

    async def get(self, profile_id: uuid.UUID) -> SeriesProfile | None:
        """Fetch a series profile by identifier."""
        raise NotImplementedError

    async def get_by_slug(self, slug: str) -> SeriesProfile | None:
        """Fetch a series profile by slug."""
        raise NotImplementedError

    async def list(self) -> cabc.Sequence[SeriesProfile]:
        """List all series profiles."""
        raise NotImplementedError

    async def update(self, profile: SeriesProfile) -> None:
        """Persist changes to an existing series profile."""
        raise NotImplementedError


class TeiHeaderRepository(typ.Protocol):
    """Persistence interface for TEI headers."""

    async def add(self, header: TeiHeader) -> None:
        """Persist a TEI header."""
        raise NotImplementedError

    async def get(self, header_id: uuid.UUID) -> TeiHeader | None:
        """Fetch a TEI header by identifier."""
        raise NotImplementedError


class EpisodeRepository(typ.Protocol):
    """Persistence interface for canonical episodes."""

    async def add(self, episode: CanonicalEpisode) -> None:
        """Persist a canonical episode."""
        raise NotImplementedError

    async def get(self, episode_id: uuid.UUID) -> CanonicalEpisode | None:
        """Fetch a canonical episode by identifier."""
        raise NotImplementedError

    async def list_by_ids(
        self, episode_ids: cabc.Collection[uuid.UUID]
    ) -> list[CanonicalEpisode]:
        """Fetch canonical episodes by identifiers."""
        raise NotImplementedError

    async def update(
        self,
        episode_id: uuid.UUID,
        *,
        update: EpisodeTeiUpdate,
    ) -> CanonicalEpisode:
        """Update episode TEI with an optimistic revision precondition."""
        raise NotImplementedError


class IngestionJobRepository(typ.Protocol):
    """Persistence interface for ingestion jobs."""

    async def add(self, job: IngestionJob) -> None:
        """Persist an ingestion job."""
        raise NotImplementedError

    async def get(self, job_id: uuid.UUID) -> IngestionJob | None:
        """Fetch an ingestion job by identifier."""
        raise NotImplementedError

    async def get_for_update(self, job_id: uuid.UUID) -> IngestionJob | None:
        """Fetch and lock an ingestion job for transactional mutation."""
        raise NotImplementedError

    async def set_target_episode(
        self,
        job_id: uuid.UUID,
        *,
        episode_id: uuid.UUID,
    ) -> None:
        """Associate an ingestion job with its materialized episode."""
        raise NotImplementedError

    async def list_paged(
        self,
        filters: IngestionJobListFilters,
        *,
        limit: int,
        offset: int,
    ) -> cabc.Sequence[IngestionJob]:
        """List ingestion jobs using source-intake filters."""
        raise NotImplementedError

    async def count(
        self,
        filters: IngestionJobListFilters,
    ) -> int:
        """Count ingestion jobs using source-intake filters."""
        raise NotImplementedError

    async def transition_intake_state(
        self,
        job_id: uuid.UUID,
        *,
        from_state: IntakeState,
        to_state: IntakeState,
    ) -> bool:
        """Return True only when the conditional intake-state update matched."""
        raise NotImplementedError


class SourceDocumentRepository(typ.Protocol):
    """Persistence interface for source documents."""

    async def add(self, document: SourceDocument) -> None:
        """Persist a source document."""
        raise NotImplementedError

    async def list_for_job(self, job_id: uuid.UUID) -> list[SourceDocument]:
        """List source documents for an ingestion job."""
        raise NotImplementedError


class ApprovalEventRepository(typ.Protocol):
    """Persistence interface for approval events."""

    async def add(self, event: ApprovalEvent) -> None:
        """Persist an approval event."""
        raise NotImplementedError

    async def list_for_episode(
        self,
        episode_id: uuid.UUID,
    ) -> list[ApprovalEvent]:
        """List approval events for a canonical episode."""
        raise NotImplementedError


class EpisodeTemplateRepository(typ.Protocol):
    """Persistence interface for episode templates."""

    async def add(self, template: EpisodeTemplate) -> None:
        """Persist an episode template."""
        raise NotImplementedError

    async def get(self, template_id: uuid.UUID) -> EpisodeTemplate | None:
        """Fetch an episode template by identifier."""
        raise NotImplementedError

    async def list(
        self,
        series_profile_id: uuid.UUID | None,
    ) -> cabc.Sequence[EpisodeTemplate]:
        """List episode templates, optionally filtered by series profile."""
        raise NotImplementedError

    async def get_by_slug(
        self,
        series_profile_id: uuid.UUID,
        slug: str,
    ) -> EpisodeTemplate | None:
        """Fetch an episode template by series profile and slug."""
        raise NotImplementedError

    async def update(self, template: EpisodeTemplate) -> None:
        """Persist changes to an existing episode template."""
        raise NotImplementedError
