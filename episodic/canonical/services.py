"""Domain services for canonical content ingestion."""

from __future__ import annotations

import datetime as dt
import typing as typ
import uuid

from episodic.logging import get_logger, log_info

from .domain import (
    ApprovalEvent,
    ApprovalState,
    CanonicalEpisode,
    EpisodeStatus,
    IngestionJob,
    IngestionRequest,
    IngestionStatus,
    SeriesProfile,
    SourceDocument,
    TeiHeader,
)
from .tei import TeiHeaderPayload, parse_tei_header

logger = get_logger(__name__)

if typ.TYPE_CHECKING:
    from .ports import CanonicalUnitOfWork


def _create_tei_header(
    header_id: uuid.UUID,
    header_payload: TeiHeaderPayload,
    tei_xml: str,
    now: dt.datetime,
) -> TeiHeader:
    """Create a TEI header entity."""
    return TeiHeader(
        id=header_id,
        title=header_payload.title,
        payload=header_payload.payload,
        raw_xml=tei_xml,
        created_at=now,
        updated_at=now,
    )


def _create_canonical_episode(  # noqa: PLR0913, PLR0917  # TODO(@codex): https://github.com/leynos/episodic/pull/14 - required entity fields.
    episode_id: uuid.UUID,
    series_profile_id: uuid.UUID,
    header_id: uuid.UUID,
    title: str,
    tei_xml: str,
    now: dt.datetime,
) -> CanonicalEpisode:
    """Create a canonical episode entity."""
    return CanonicalEpisode(
        id=episode_id,
        series_profile_id=series_profile_id,
        tei_header_id=header_id,
        title=title,
        tei_xml=tei_xml,
        status=EpisodeStatus.DRAFT,
        approval_state=ApprovalState.DRAFT,
        created_at=now,
        updated_at=now,
    )


def _create_ingestion_job(
    job_id: uuid.UUID,
    series_profile_id: uuid.UUID,
    episode_id: uuid.UUID,
    now: dt.datetime,
) -> IngestionJob:
    """Create an ingestion job entity."""
    return IngestionJob(
        id=job_id,
        series_profile_id=series_profile_id,
        target_episode_id=episode_id,
        status=IngestionStatus.COMPLETED,
        requested_at=now,
        started_at=now,
        completed_at=now,
        error_message=None,
        created_at=now,
        updated_at=now,
    )


def _create_source_documents(
    request: IngestionRequest,
    job_id: uuid.UUID,
    episode_id: uuid.UUID,
    now: dt.datetime,
) -> list[SourceDocument]:
    """Create source document entities for an ingestion request."""
    return [
        SourceDocument(
            id=uuid.uuid4(),
            ingestion_job_id=job_id,
            canonical_episode_id=episode_id,
            source_type=source.source_type,
            source_uri=source.source_uri,
            weight=source.weight,
            content_hash=source.content_hash,
            metadata=source.metadata,
            created_at=now,
        )
        for source in request.sources
    ]


def _create_initial_approval_event(
    episode_id: uuid.UUID,
    request: IngestionRequest,
    now: dt.datetime,
) -> ApprovalEvent:
    """Create the initial approval event entity."""
    return ApprovalEvent(
        id=uuid.uuid4(),
        episode_id=episode_id,
        actor=request.requested_by,
        from_state=None,
        to_state=ApprovalState.DRAFT,
        note="Initial ingestion.",
        payload={"sources": [source.source_uri for source in request.sources]},
        created_at=now,
    )


async def ingest_sources(
    uow: CanonicalUnitOfWork,
    series_profile: SeriesProfile,
    request: IngestionRequest,
) -> CanonicalEpisode:
    """Create canonical records for an ingestion job.

    Parameters
    ----------
    uow : CanonicalUnitOfWork
        Unit-of-work boundary providing repository access and transaction scope.
    series_profile : SeriesProfile
        Series profile that owns the canonical episode.
    request : IngestionRequest
        Ingestion payload containing TEI XML and source metadata.

    Returns
    -------
    CanonicalEpisode
        Persisted canonical episode representing the ingested TEI content.

    Raises
    ------
    TypeError
        If the TEI header is missing from the parsed payload.
    ValueError
        If the TEI header title is missing or blank.

    Notes
    -----
    This function writes TEI headers, episodes, ingestion jobs, source
    documents, and approval events via the unit-of-work and commits the
    transaction.
    """
    now = dt.datetime.now(dt.UTC)
    header_payload = parse_tei_header(request.tei_xml)
    header_id = uuid.uuid4()
    episode_id = uuid.uuid4()
    job_id = uuid.uuid4()

    header = _create_tei_header(header_id, header_payload, request.tei_xml, now)
    episode = _create_canonical_episode(
        episode_id,
        series_profile.id,
        header_id,
        header_payload.title,
        request.tei_xml,
        now,
    )
    job = _create_ingestion_job(job_id, series_profile.id, episode_id, now)

    await uow.tei_headers.add(header)
    await uow.flush()
    await uow.episodes.add(episode)
    await uow.ingestion_jobs.add(job)

    documents = _create_source_documents(request, job_id, episode_id, now)
    for document in documents:
        await uow.source_documents.add(document)

    await uow.flush()

    event = _create_initial_approval_event(episode_id, request, now)
    await uow.approval_events.add(event)

    await uow.commit()
    log_info(
        logger,
        "Ingested %s sources into canonical episode %s.",
        len(request.sources),
        episode_id,
    )

    return episode
