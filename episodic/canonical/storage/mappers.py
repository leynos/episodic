"""Record-to-domain mapping helpers for canonical persistence.

This module converts SQLAlchemy ORM records into domain entities. The helpers
keep mapping logic centralized so repositories can remain focused on data
access.

Examples
--------
Convert a record to a domain entity:

>>> entity = _series_profile_from_record(record)
"""

from __future__ import annotations

import typing as typ

from episodic.canonical.domain import (
    ApprovalEvent,
    CanonicalEpisode,
    EpisodeTemplate,
    EpisodeTemplateHistoryEntry,
    IngestionJob,
    SeriesProfile,
    SeriesProfileHistoryEntry,
    SourceDocument,
    TeiHeader,
)

if typ.TYPE_CHECKING:
    from episodic.canonical.storage.models import (
        ApprovalEventRecord,
        EpisodeRecord,
        EpisodeTemplateHistoryRecord,
        EpisodeTemplateRecord,
        IngestionJobRecord,
        SeriesProfileHistoryRecord,
        SeriesProfileRecord,
        SourceDocumentRecord,
        TeiHeaderRecord,
    )


def _series_profile_from_record(record: SeriesProfileRecord) -> SeriesProfile:
    """Map a series profile record to a domain entity."""
    return SeriesProfile(
        id=record.id,
        slug=record.slug,
        title=record.title,
        description=record.description,
        configuration=record.configuration,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _tei_header_from_record(record: TeiHeaderRecord) -> TeiHeader:
    """Map a TEI header record to a domain entity."""
    return TeiHeader(
        id=record.id,
        title=record.title,
        payload=record.payload,
        raw_xml=record.raw_xml,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _episode_from_record(record: EpisodeRecord) -> CanonicalEpisode:
    """Map an episode record to a domain entity."""
    return CanonicalEpisode(
        id=record.id,
        series_profile_id=record.series_profile_id,
        tei_header_id=record.tei_header_id,
        title=record.title,
        tei_xml=record.tei_xml,
        status=record.status,
        approval_state=record.approval_state,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _ingestion_job_from_record(record: IngestionJobRecord) -> IngestionJob:
    """Map an ingestion job record to a domain entity."""
    return IngestionJob(
        id=record.id,
        series_profile_id=record.series_profile_id,
        target_episode_id=record.target_episode_id,
        status=record.status,
        requested_at=record.requested_at,
        started_at=record.started_at,
        completed_at=record.completed_at,
        error_message=record.error_message,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _source_document_from_record(
    record: SourceDocumentRecord,
) -> SourceDocument:
    """Map a source document record to a domain entity."""
    return SourceDocument(
        id=record.id,
        ingestion_job_id=record.ingestion_job_id,
        canonical_episode_id=record.canonical_episode_id,
        source_type=record.source_type,
        source_uri=record.source_uri,
        weight=record.weight,
        content_hash=record.content_hash,
        metadata=record.metadata_payload,
        created_at=record.created_at,
    )


def _approval_event_from_record(record: ApprovalEventRecord) -> ApprovalEvent:
    """Map an approval event record to a domain entity."""
    return ApprovalEvent(
        id=record.id,
        episode_id=record.episode_id,
        actor=record.actor,
        from_state=record.from_state,
        to_state=record.to_state,
        note=record.note,
        payload=record.payload,
        created_at=record.created_at,
    )


def _episode_template_from_record(record: EpisodeTemplateRecord) -> EpisodeTemplate:
    """Map an episode template record to a domain entity."""
    return EpisodeTemplate(
        id=record.id,
        series_profile_id=record.series_profile_id,
        slug=record.slug,
        title=record.title,
        description=record.description,
        structure=record.structure,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _series_profile_history_from_record(
    record: SeriesProfileHistoryRecord,
) -> SeriesProfileHistoryEntry:
    """Map a series profile history record to a domain entity."""
    return SeriesProfileHistoryEntry(
        id=record.id,
        series_profile_id=record.series_profile_id,
        revision=record.revision,
        actor=record.actor,
        note=record.note,
        snapshot=record.snapshot,
        created_at=record.created_at,
    )


def _episode_template_history_from_record(
    record: EpisodeTemplateHistoryRecord,
) -> EpisodeTemplateHistoryEntry:
    """Map an episode template history record to a domain entity."""
    return EpisodeTemplateHistoryEntry(
        id=record.id,
        episode_template_id=record.episode_template_id,
        revision=record.revision,
        actor=record.actor,
        note=record.note,
        snapshot=record.snapshot,
        created_at=record.created_at,
    )
