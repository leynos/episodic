"""Domain services for canonical content ingestion.

This module provides orchestration helpers for ingesting TEI content into the
canonical persistence layer using unit-of-work boundaries.

Examples
--------
Ingest sources within a unit-of-work session:

>>> async with SqlAlchemyUnitOfWork(session_factory) as uow:
...     episode = await ingest_sources(
...         uow=uow,
...         series_profile=profile,
...         request=request,
...     )
"""

import dataclasses as dc
import datetime as dt
import typing as typ
import uuid

from episodic.logging import get_logger, log_info

from . import reference_documents
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
from .provenance import build_tei_header_provenance, merge_tei_header_provenance
from .tei import TeiHeaderPayload, parse_tei_header

logger = get_logger(__name__)

if typ.TYPE_CHECKING:
    from .ports import CanonicalUnitOfWork


def _new_storage_id() -> uuid.UUID:
    """Create a monotonic storage identifier for persisted canonical records."""
    return uuid.uuid7()


def _with_ingestion_provenance(
    header_payload: TeiHeaderPayload,
    request: IngestionRequest,
    captured_at: dt.datetime,
) -> TeiHeaderPayload:
    """Return a TEI header payload enriched with ingestion provenance."""
    reviewer_identities = [request.requested_by] if request.requested_by else []
    provenance = build_tei_header_provenance(
        sources=request.sources,
        captured_at=captured_at,
        reviewer_identities=reviewer_identities,
        capture_context="source_ingestion",
    )
    return dc.replace(
        header_payload,
        payload=merge_tei_header_provenance(
            payload=header_payload.payload,
            provenance=provenance,
        ),
    )


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


def _create_canonical_episode(
    episode_id: uuid.UUID,
    series_profile: SeriesProfile,
    header: TeiHeader,
    now: dt.datetime,
) -> CanonicalEpisode:
    """Create a canonical episode entity."""
    return CanonicalEpisode(
        id=episode_id,
        series_profile_id=series_profile.id,
        tei_header_id=header.id,
        title=header.title,
        tei_xml=header.raw_xml,
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
            id=_new_storage_id(),
            ingestion_job_id=job_id,
            canonical_episode_id=episode_id,
            reference_document_revision_id=source.reference_document_revision_id,
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
        id=_new_storage_id(),
        episode_id=episode_id,
        actor=request.requested_by,
        from_state=None,
        to_state=ApprovalState.DRAFT,
        note="Initial ingestion.",
        payload={"sources": [source.source_uri for source in request.sources]},
        created_at=now,
    )


@dc.dataclass(frozen=True)
class _IngestionContext:
    job_id: uuid.UUID
    episode_id: uuid.UUID
    now: dt.datetime


async def _persist_source_documents_and_snapshot_bindings(
    uow: CanonicalUnitOfWork,
    series_profile: SeriesProfile,
    request: IngestionRequest,
    context: _IngestionContext,
) -> None:
    """Persist source documents and snapshot resolved reference bindings."""
    documents = _create_source_documents(
        request, context.job_id, context.episode_id, context.now
    )
    for document in documents:
        await uow.source_documents.add(document)

    await uow.flush()

    resolved_bindings = await reference_documents.resolve_bindings(
        uow,
        series_profile_id=series_profile.id,
        template_id=request.episode_template_id,
        episode_id=context.episode_id,
    )
    await reference_documents.snapshot_resolved_bindings(
        uow,
        resolved=resolved_bindings,
        ingestion_job_id=context.job_id,
        canonical_episode_id=context.episode_id,
    )


async def ingest_sources(
    uow: CanonicalUnitOfWork,
    series_profile: SeriesProfile,
    request: IngestionRequest,
) -> CanonicalEpisode:
    """Create canonical records for an ingestion job."""
    now = dt.datetime.now(dt.UTC)
    header_payload = parse_tei_header(request.tei_xml)
    header_payload = _with_ingestion_provenance(
        header_payload=header_payload,
        request=request,
        captured_at=now,
    )
    header_id = _new_storage_id()
    episode_id = _new_storage_id()
    job_id = _new_storage_id()

    header = _create_tei_header(header_id, header_payload, request.tei_xml, now)
    episode = _create_canonical_episode(episode_id, series_profile, header, now)
    job = _create_ingestion_job(job_id, series_profile.id, episode_id, now)

    await uow.tei_headers.add(header)
    await uow.flush()
    await uow.episodes.add(episode)
    await uow.ingestion_jobs.add(job)
    context = _IngestionContext(job_id=job_id, episode_id=episode_id, now=now)
    await _persist_source_documents_and_snapshot_bindings(
        uow, series_profile, request, context
    )

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
