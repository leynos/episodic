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
from .tei import parse_tei_header

logger = get_logger(__name__)

if typ.TYPE_CHECKING:
    from .ports import CanonicalUnitOfWork


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

    header = TeiHeader(
        id=header_id,
        title=header_payload.title,
        payload=header_payload.payload,
        raw_xml=request.tei_xml,
        created_at=now,
        updated_at=now,
    )
    episode = CanonicalEpisode(
        id=episode_id,
        series_profile_id=series_profile.id,
        tei_header_id=header_id,
        title=header_payload.title,
        tei_xml=request.tei_xml,
        status=EpisodeStatus.DRAFT,
        approval_state=ApprovalState.DRAFT,
        created_at=now,
        updated_at=now,
    )
    job = IngestionJob(
        id=job_id,
        series_profile_id=series_profile.id,
        target_episode_id=episode_id,
        status=IngestionStatus.COMPLETED,
        requested_at=now,
        started_at=now,
        completed_at=now,
        error_message=None,
        created_at=now,
        updated_at=now,
    )

    await uow.tei_headers.add(header)
    await uow.flush()
    await uow.episodes.add(episode)
    await uow.ingestion_jobs.add(job)

    for source in request.sources:
        document = SourceDocument(
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
        await uow.source_documents.add(document)

    await uow.flush()

    event = ApprovalEvent(
        id=uuid.uuid4(),
        episode_id=episode_id,
        actor=request.requested_by,
        from_state=None,
        to_state=ApprovalState.DRAFT,
        note="Initial ingestion.",
        payload={"sources": [source.source_uri for source in request.sources]},
        created_at=now,
    )
    await uow.approval_events.add(event)

    await uow.commit()
    log_info(
        logger,
        "Ingested %s sources into canonical episode %s.",
        len(request.sources),
        episode_id,
    )

    return episode
