"""Record-to-domain mappers for reusable reference documents."""

from episodic.canonical.domain import (
    ReferenceBinding,
    ReferenceDocument,
    ReferenceDocumentRevision,
)

from .reference_models import (
    ReferenceBindingRecord,
    ReferenceDocumentRecord,
    ReferenceDocumentRevisionRecord,
)


def _reference_document_from_record(
    record: ReferenceDocumentRecord,
) -> ReferenceDocument:
    """Map a reusable reference document record to a domain entity."""
    return ReferenceDocument(
        id=record.id,
        owner_series_profile_id=record.owner_series_profile_id,
        kind=record.kind,
        lifecycle_state=record.lifecycle_state,
        metadata=record.metadata_payload,
        created_at=record.created_at,
        updated_at=record.updated_at,
        lock_version=record.lock_version,
    )


def _reference_document_to_record(
    document: ReferenceDocument,
) -> ReferenceDocumentRecord:
    """Map a reusable reference document domain entity to a record."""
    return ReferenceDocumentRecord(
        id=document.id,
        owner_series_profile_id=document.owner_series_profile_id,
        kind=document.kind,
        lifecycle_state=document.lifecycle_state,
        metadata_payload=document.metadata,
        created_at=document.created_at,
        updated_at=document.updated_at,
        lock_version=document.lock_version,
    )


def _reference_document_revision_from_record(
    record: ReferenceDocumentRevisionRecord,
) -> ReferenceDocumentRevision:
    """Map a reusable reference revision record to a domain entity."""
    return ReferenceDocumentRevision(
        id=record.id,
        reference_document_id=record.reference_document_id,
        content=record.content_payload,
        content_hash=record.content_hash,
        author=record.author,
        change_note=record.change_note,
        created_at=record.created_at,
    )


def _reference_document_revision_to_record(
    revision: ReferenceDocumentRevision,
) -> ReferenceDocumentRevisionRecord:
    """Map a reusable reference revision domain entity to a record."""
    return ReferenceDocumentRevisionRecord(
        id=revision.id,
        reference_document_id=revision.reference_document_id,
        content_payload=revision.content,
        content_hash=revision.content_hash,
        author=revision.author,
        change_note=revision.change_note,
        created_at=revision.created_at,
    )


def _reference_binding_from_record(
    record: ReferenceBindingRecord,
) -> ReferenceBinding:
    """Map a reusable reference binding record to a domain entity."""
    return ReferenceBinding(
        id=record.id,
        reference_document_revision_id=record.reference_document_revision_id,
        target_kind=record.target_kind,
        series_profile_id=record.series_profile_id,
        episode_template_id=record.episode_template_id,
        ingestion_job_id=record.ingestion_job_id,
        effective_from_episode_id=record.effective_from_episode_id,
        created_at=record.created_at,
    )


def _reference_binding_to_record(
    binding: ReferenceBinding,
) -> ReferenceBindingRecord:
    """Map a reusable reference binding domain entity to a record."""
    return ReferenceBindingRecord(
        id=binding.id,
        reference_document_revision_id=binding.reference_document_revision_id,
        target_kind=binding.target_kind,
        series_profile_id=binding.series_profile_id,
        episode_template_id=binding.episode_template_id,
        ingestion_job_id=binding.ingestion_job_id,
        effective_from_episode_id=binding.effective_from_episode_id,
        created_at=binding.created_at,
    )
