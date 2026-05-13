"""Record-to-domain mappers for core canonical entities."""

import copy

from episodic.canonical.domain import (
    ApprovalEvent,
    CanonicalEpisode,
    EpisodeTemplate,
    IngestionJob,
    SeriesProfile,
    SourceDocument,
    TeiHeader,
)

from .compression import decode_text_from_storage, encode_text_for_storage
from .entity_models import (
    ApprovalEventRecord,
    EpisodeRecord,
    IngestionJobRecord,
    SourceDocumentRecord,
    TeiHeaderRecord,
)
from .profile_models import EpisodeTemplateRecord, SeriesProfileRecord


def _series_profile_from_record(record: SeriesProfileRecord) -> SeriesProfile:
    """Map a series profile record to a domain entity."""
    return SeriesProfile(
        id=record.id,
        slug=record.slug,
        title=record.title,
        description=record.description,
        configuration=record.configuration,
        guardrails=copy.deepcopy(record.guardrails),
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _series_profile_to_record(profile: SeriesProfile) -> SeriesProfileRecord:
    """Map a series profile domain entity to a record."""
    return SeriesProfileRecord(
        id=profile.id,
        slug=profile.slug,
        title=profile.title,
        description=profile.description,
        configuration=profile.configuration,
        guardrails=copy.deepcopy(profile.guardrails),
        created_at=profile.created_at,
        updated_at=profile.updated_at,
    )


def _tei_header_from_record(record: TeiHeaderRecord) -> TeiHeader:
    """Map a TEI header record to a domain entity."""
    return TeiHeader(
        id=record.id,
        title=record.title,
        payload=record.payload,
        raw_xml=decode_text_from_storage(
            text_value=record.raw_xml,
            compressed_value=record.raw_xml_zstd,
            field_name="tei_headers.raw_xml",
        ),
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _tei_header_to_record(header: TeiHeader) -> TeiHeaderRecord:
    """Map a TEI header domain entity to a record."""
    raw_xml, raw_xml_zstd = encode_text_for_storage(header.raw_xml)
    return TeiHeaderRecord(
        id=header.id,
        title=header.title,
        payload=header.payload,
        raw_xml=raw_xml,
        raw_xml_zstd=raw_xml_zstd,
        created_at=header.created_at,
        updated_at=header.updated_at,
    )


def _episode_from_record(record: EpisodeRecord) -> CanonicalEpisode:
    """Map an episode record to a domain entity."""
    return CanonicalEpisode(
        id=record.id,
        series_profile_id=record.series_profile_id,
        tei_header_id=record.tei_header_id,
        title=record.title,
        tei_xml=decode_text_from_storage(
            text_value=record.tei_xml,
            compressed_value=record.tei_xml_zstd,
            field_name="episodes.tei_xml",
        ),
        status=record.status,
        approval_state=record.approval_state,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _episode_to_record(episode: CanonicalEpisode) -> EpisodeRecord:
    """Map a canonical episode domain entity to a record."""
    tei_xml, tei_xml_zstd = encode_text_for_storage(episode.tei_xml)
    return EpisodeRecord(
        id=episode.id,
        series_profile_id=episode.series_profile_id,
        tei_header_id=episode.tei_header_id,
        title=episode.title,
        tei_xml=tei_xml,
        tei_xml_zstd=tei_xml_zstd,
        status=episode.status,
        approval_state=episode.approval_state,
        created_at=episode.created_at,
        updated_at=episode.updated_at,
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


def _ingestion_job_to_record(job: IngestionJob) -> IngestionJobRecord:
    """Map an ingestion job domain entity to a record."""
    return IngestionJobRecord(
        id=job.id,
        series_profile_id=job.series_profile_id,
        target_episode_id=job.target_episode_id,
        status=job.status,
        requested_at=job.requested_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
        error_message=job.error_message,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


def _source_document_from_record(
    record: SourceDocumentRecord,
) -> SourceDocument:
    """Map a source document record to a domain entity."""
    return SourceDocument(
        id=record.id,
        ingestion_job_id=record.ingestion_job_id,
        canonical_episode_id=record.canonical_episode_id,
        reference_document_revision_id=record.reference_document_revision_id,
        source_type=record.source_type,
        source_uri=record.source_uri,
        weight=record.weight,
        content_hash=record.content_hash,
        metadata=record.metadata_payload,
        created_at=record.created_at,
    )


def _source_document_to_record(document: SourceDocument) -> SourceDocumentRecord:
    """Map a source document domain entity to a record."""
    return SourceDocumentRecord(
        id=document.id,
        ingestion_job_id=document.ingestion_job_id,
        canonical_episode_id=document.canonical_episode_id,
        reference_document_revision_id=document.reference_document_revision_id,
        source_type=document.source_type,
        source_uri=document.source_uri,
        weight=document.weight,
        content_hash=document.content_hash,
        metadata_payload=document.metadata,
        created_at=document.created_at,
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


def _approval_event_to_record(event: ApprovalEvent) -> ApprovalEventRecord:
    """Map an approval event domain entity to a record."""
    return ApprovalEventRecord(
        id=event.id,
        episode_id=event.episode_id,
        actor=event.actor,
        from_state=event.from_state,
        to_state=event.to_state,
        note=event.note,
        payload=event.payload,
        created_at=event.created_at,
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
        guardrails=copy.deepcopy(record.guardrails),
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def _episode_template_to_record(template: EpisodeTemplate) -> EpisodeTemplateRecord:
    """Map an episode template domain entity to a record."""
    return EpisodeTemplateRecord(
        id=template.id,
        series_profile_id=template.series_profile_id,
        slug=template.slug,
        title=template.title,
        description=template.description,
        structure=template.structure,
        guardrails=copy.deepcopy(template.guardrails),
        created_at=template.created_at,
        updated_at=template.updated_at,
    )
