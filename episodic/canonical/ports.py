"""Ports for canonical content persistence."""

from __future__ import annotations

import typing as typ

if typ.TYPE_CHECKING:
    import uuid
    from types import TracebackType

    from .domain import (
        ApprovalEvent,
        CanonicalEpisode,
        IngestionJob,
        SeriesProfile,
        SourceDocument,
        TeiHeader,
    )


class SeriesProfileRepository(typ.Protocol):
    """Persistence interface for series profiles."""

    async def add(self, profile: SeriesProfile) -> None:
        """Persist a series profile."""
        ...

    async def get(self, profile_id: uuid.UUID) -> SeriesProfile | None:
        """Fetch a series profile by identifier."""
        ...

    async def get_by_slug(self, slug: str) -> SeriesProfile | None:
        """Fetch a series profile by slug."""
        ...


class TeiHeaderRepository(typ.Protocol):
    """Persistence interface for TEI headers."""

    async def add(self, header: TeiHeader) -> None:
        """Persist a TEI header."""

    async def get(self, header_id: uuid.UUID) -> TeiHeader | None:
        """Fetch a TEI header by identifier."""


class EpisodeRepository(typ.Protocol):
    """Persistence interface for canonical episodes."""

    async def add(self, episode: CanonicalEpisode) -> None:
        """Persist a canonical episode."""

    async def get(self, episode_id: uuid.UUID) -> CanonicalEpisode | None:
        """Fetch a canonical episode by identifier."""


class IngestionJobRepository(typ.Protocol):
    """Persistence interface for ingestion jobs."""

    async def add(self, job: IngestionJob) -> None:
        """Persist an ingestion job."""

    async def get(self, job_id: uuid.UUID) -> IngestionJob | None:
        """Fetch an ingestion job by identifier."""


class SourceDocumentRepository(typ.Protocol):
    """Persistence interface for source documents."""

    async def add(self, document: SourceDocument) -> None:
        """Persist a source document."""

    async def list_for_job(self, job_id: uuid.UUID) -> list[SourceDocument]:
        """List source documents for an ingestion job."""


class ApprovalEventRepository(typ.Protocol):
    """Persistence interface for approval events."""

    async def add(self, event: ApprovalEvent) -> None:
        """Persist an approval event."""

    async def list_for_episode(
        self,
        episode_id: uuid.UUID,
    ) -> list[ApprovalEvent]:
        """List approval events for an episode."""


class CanonicalUnitOfWork(typ.Protocol):
    """Unit of work boundary for canonical persistence."""

    series_profiles: SeriesProfileRepository
    tei_headers: TeiHeaderRepository
    episodes: EpisodeRepository
    ingestion_jobs: IngestionJobRepository
    source_documents: SourceDocumentRepository
    approval_events: ApprovalEventRepository

    async def __aenter__(self) -> CanonicalUnitOfWork:
        """Enter the unit-of-work context."""

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Exit the unit-of-work context."""

    async def commit(self) -> None:
        """Commit the current unit-of-work transaction."""

    async def flush(self) -> None:
        """Flush pending changes without committing."""

    async def rollback(self) -> None:
        """Roll back the current unit-of-work transaction."""
