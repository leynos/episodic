"""Ports for canonical content persistence.

This module defines protocol interfaces for canonical persistence boundaries so
adapters can be swapped without impacting the domain layer.

Examples
--------
Implement a repository that satisfies the protocol:

>>> class MemorySeriesProfileRepository(SeriesProfileRepository):
...     async def add(self, profile: SeriesProfile) -> None:
...         self._items[profile.id] = profile
"""

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
    """Persistence interface for series profiles.

    Methods
    -------
    add(profile)
        Persist a series profile entity.
    get(profile_id)
        Fetch a series profile by identifier.
    get_by_slug(slug)
        Fetch a series profile by slug.
    """

    async def add(self, profile: SeriesProfile) -> None:
        """Persist a series profile.

        Parameters
        ----------
        profile : SeriesProfile
            Series profile entity to persist.

        Returns
        -------
        None
        """
        ...

    async def get(self, profile_id: uuid.UUID) -> SeriesProfile | None:
        """Fetch a series profile by identifier.

        Parameters
        ----------
        profile_id : uuid.UUID
            Identifier for the series profile.

        Returns
        -------
        SeriesProfile | None
            The matching series profile, or ``None`` if no match exists.
        """
        ...

    async def get_by_slug(self, slug: str) -> SeriesProfile | None:
        """Fetch a series profile by slug.

        Parameters
        ----------
        slug : str
            Slug to match against stored series profiles.

        Returns
        -------
        SeriesProfile | None
            The matching series profile, or ``None`` if no match exists.
        """
        ...


class TeiHeaderRepository(typ.Protocol):
    """Persistence interface for TEI headers.

    Methods
    -------
    add(header)
        Persist a TEI header entity.
    get(header_id)
        Fetch a TEI header by identifier.
    """

    async def add(self, header: TeiHeader) -> None:
        """Persist a TEI header.

        Parameters
        ----------
        header : TeiHeader
            TEI header entity to persist.

        Returns
        -------
        None
        """
        ...

    async def get(self, header_id: uuid.UUID) -> TeiHeader | None:
        """Fetch a TEI header by identifier.

        Parameters
        ----------
        header_id : uuid.UUID
            Identifier for the TEI header.

        Returns
        -------
        TeiHeader | None
            The matching TEI header, or ``None`` if no match exists.
        """
        ...


class EpisodeRepository(typ.Protocol):
    """Persistence interface for canonical episodes.

    Methods
    -------
    add(episode)
        Persist a canonical episode entity.
    get(episode_id)
        Fetch a canonical episode by identifier.
    """

    async def add(self, episode: CanonicalEpisode) -> None:
        """Persist a canonical episode.

        Parameters
        ----------
        episode : CanonicalEpisode
            Canonical episode entity to persist.

        Returns
        -------
        None
        """
        ...

    async def get(self, episode_id: uuid.UUID) -> CanonicalEpisode | None:
        """Fetch a canonical episode by identifier.

        Parameters
        ----------
        episode_id : uuid.UUID
            Identifier for the canonical episode.

        Returns
        -------
        CanonicalEpisode | None
            The matching canonical episode, or ``None`` if no match exists.
        """
        ...


class IngestionJobRepository(typ.Protocol):
    """Persistence interface for ingestion jobs.

    Methods
    -------
    add(job)
        Persist an ingestion job entity.
    get(job_id)
        Fetch an ingestion job by identifier.
    """

    async def add(self, job: IngestionJob) -> None:
        """Persist an ingestion job.

        Parameters
        ----------
        job : IngestionJob
            Ingestion job entity to persist.

        Returns
        -------
        None
        """
        ...

    async def get(self, job_id: uuid.UUID) -> IngestionJob | None:
        """Fetch an ingestion job by identifier.

        Parameters
        ----------
        job_id : uuid.UUID
            Identifier for the ingestion job.

        Returns
        -------
        IngestionJob | None
            The matching ingestion job, or ``None`` if no match exists.
        """
        ...


class SourceDocumentRepository(typ.Protocol):
    """Persistence interface for source documents.

    Methods
    -------
    add(document)
        Persist a source document entity.
    list_for_job(job_id)
        List source documents for an ingestion job.
    """

    async def add(self, document: SourceDocument) -> None:
        """Persist a source document.

        Parameters
        ----------
        document : SourceDocument
            Source document entity to persist.

        Returns
        -------
        None
        """
        ...

    async def list_for_job(self, job_id: uuid.UUID) -> list[SourceDocument]:
        """List source documents for an ingestion job.

        Parameters
        ----------
        job_id : uuid.UUID
            Identifier for the ingestion job.

        Returns
        -------
        list[SourceDocument]
            Source documents associated with the ingestion job.
        """
        ...


class ApprovalEventRepository(typ.Protocol):
    """Persistence interface for approval events.

    Methods
    -------
    add(event)
        Persist an approval event entity.
    list_for_episode(episode_id)
        List approval events for a canonical episode.
    """

    async def add(self, event: ApprovalEvent) -> None:
        """Persist an approval event.

        Parameters
        ----------
        event : ApprovalEvent
            Approval event entity to persist.

        Returns
        -------
        None
        """
        ...

    async def list_for_episode(
        self,
        episode_id: uuid.UUID,
    ) -> list[ApprovalEvent]:
        """List approval events for a canonical episode.

        Parameters
        ----------
        episode_id : uuid.UUID
            Identifier for the canonical episode.

        Returns
        -------
        list[ApprovalEvent]
            Approval events associated with the canonical episode.
        """
        ...


class CanonicalUnitOfWork(typ.Protocol):
    """Unit-of-work boundary for canonical persistence.

    Attributes
    ----------
    series_profiles : SeriesProfileRepository
        Repository for series profile persistence.
    tei_headers : TeiHeaderRepository
        Repository for TEI header persistence.
    episodes : EpisodeRepository
        Repository for canonical episode persistence.
    ingestion_jobs : IngestionJobRepository
        Repository for ingestion job persistence.
    source_documents : SourceDocumentRepository
        Repository for source document persistence.
    approval_events : ApprovalEventRepository
        Repository for approval event persistence.
    """

    series_profiles: SeriesProfileRepository
    tei_headers: TeiHeaderRepository
    episodes: EpisodeRepository
    ingestion_jobs: IngestionJobRepository
    source_documents: SourceDocumentRepository
    approval_events: ApprovalEventRepository

    async def __aenter__(self) -> CanonicalUnitOfWork:
        """Enter the unit-of-work context.

        Returns
        -------
        CanonicalUnitOfWork
            The active unit-of-work instance.
        """
        ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Exit the unit-of-work context.

        Parameters
        ----------
        exc_type : type[BaseException] | None
            Exception type raised within the context, if any.
        exc : BaseException | None
            Exception instance raised within the context, if any.
        traceback : TracebackType | None
            Traceback for the raised exception, if any.

        Returns
        -------
        None
        """
        ...

    async def commit(self) -> None:
        """Commit the current unit-of-work transaction.

        Returns
        -------
        None
        """
        ...

    async def flush(self) -> None:
        """Flush pending changes without committing.

        Returns
        -------
        None
        """
        ...

    async def rollback(self) -> None:
        """Roll back the current unit-of-work transaction.

        Returns
        -------
        None
        """
        ...
