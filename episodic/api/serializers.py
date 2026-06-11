"""Response serializers for Falcon profile and template endpoints."""

import typing as typ
import uuid  # noqa: TC003

if typ.TYPE_CHECKING:
    from episodic.canonical.domain import (
        EpisodeTemplate,
        EpisodeTemplateHistoryEntry,
        IngestionJob,
        ReferenceBinding,
        ReferenceDocument,
        ReferenceDocumentRevision,
        SeriesProfile,
        SeriesProfileHistoryEntry,
    )
    from episodic.canonical.ingestion_sources import IngestionJobSource
    from episodic.canonical.reference_documents import ResolvedBinding
    from episodic.canonical.uploads import Upload


def serialize_series_profile(
    profile: SeriesProfile, revision: int
) -> dict[str, typ.Any]:
    """Serialize a series profile response payload."""
    return {
        "id": str(profile.id),
        "slug": profile.slug,
        "title": profile.title,
        "description": profile.description,
        "configuration": profile.configuration,
        "guardrails": profile.guardrails,
        "revision": revision,
        "created_at": profile.created_at.isoformat(),
        "updated_at": profile.updated_at.isoformat(),
    }


def serialize_episode_template(
    template: EpisodeTemplate,
    revision: int,
) -> dict[str, typ.Any]:
    """Serialize an episode template response payload."""
    return {
        "id": str(template.id),
        "series_profile_id": str(template.series_profile_id),
        "slug": template.slug,
        "title": template.title,
        "description": template.description,
        "structure": template.structure,
        "guardrails": template.guardrails,
        "revision": revision,
        "created_at": template.created_at.isoformat(),
        "updated_at": template.updated_at.isoformat(),
    }


def _serialize_history_entry(
    entry: SeriesProfileHistoryEntry | EpisodeTemplateHistoryEntry,
    parent_id_field: str,
) -> dict[str, typ.Any]:
    """Serialize a history entry to JSON."""
    parent_id = getattr(entry, parent_id_field)
    return {
        "id": str(entry.id),
        parent_id_field: str(parent_id),
        "revision": entry.revision,
        "actor": entry.actor,
        "note": entry.note,
        "snapshot": entry.snapshot,
        "created_at": entry.created_at.isoformat(),
    }


def serialize_series_profile_history_entry(
    entry: SeriesProfileHistoryEntry,
) -> dict[str, typ.Any]:
    """Serialize a profile history entry."""
    return _serialize_history_entry(entry, "series_profile_id")


def serialize_episode_template_history_entry(
    entry: EpisodeTemplateHistoryEntry,
) -> dict[str, typ.Any]:
    """Serialize an episode-template history entry."""
    return _serialize_history_entry(entry, "episode_template_id")


def _optional_uuid_str(value: uuid.UUID | None) -> str | None:
    """Return the string form of a UUID, or None."""
    return None if value is None else str(value)


def serialize_reference_document(document: ReferenceDocument) -> dict[str, typ.Any]:
    """Serialize a reusable reference-document response payload."""
    return {
        "id": str(document.id),
        "owner_series_profile_id": str(document.owner_series_profile_id),
        "kind": document.kind.value,
        "lifecycle_state": document.lifecycle_state.value,
        "metadata": document.metadata,
        "lock_version": document.lock_version,
        "created_at": document.created_at.isoformat(),
        "updated_at": document.updated_at.isoformat(),
    }


def serialize_reference_document_revision(
    revision: ReferenceDocumentRevision,
) -> dict[str, typ.Any]:
    """Serialize a reusable reference-document revision payload."""
    return {
        "id": str(revision.id),
        "reference_document_id": str(revision.reference_document_id),
        "content": revision.content,
        "content_hash": revision.content_hash,
        "author": revision.author,
        "change_note": revision.change_note,
        "created_at": revision.created_at.isoformat(),
    }


def serialize_reference_binding(binding: ReferenceBinding) -> dict[str, typ.Any]:
    """Serialize a reusable reference-binding payload."""
    return {
        "id": str(binding.id),
        "reference_document_revision_id": str(binding.reference_document_revision_id),
        "target_kind": binding.target_kind.value,
        "series_profile_id": _optional_uuid_str(binding.series_profile_id),
        "episode_template_id": _optional_uuid_str(binding.episode_template_id),
        "ingestion_job_id": _optional_uuid_str(binding.ingestion_job_id),
        "effective_from_episode_id": _optional_uuid_str(
            binding.effective_from_episode_id
        ),
        "created_at": binding.created_at.isoformat(),
    }


def serialize_resolved_binding(
    resolved_binding: ResolvedBinding,
) -> dict[str, typ.Any]:
    """Serialize a resolved binding bundle for API responses."""
    return {
        "binding": serialize_reference_binding(resolved_binding.binding),
        "revision": serialize_reference_document_revision(resolved_binding.revision),
        "document": serialize_reference_document(resolved_binding.document),
    }


def serialize_upload(upload: Upload) -> dict[str, typ.Any]:
    """Serialize a source-intake upload response payload."""
    return {
        "id": str(upload.id),
        "content_hash": upload.content_hash,
        "size_bytes": upload.actual_size,
        "content_type": upload.content_type,
        "storage_key": upload.storage_key,
        "state": upload.state.value,
        "metadata": upload.metadata,
        "created_at": upload.created_at.isoformat(),
        "updated_at": upload.updated_at.isoformat(),
    }


def serialize_ingestion_job(
    job: IngestionJob,
    *,
    next_poll_after_seconds: int | None = None,
) -> dict[str, typ.Any]:
    """Serialize an intake-stage ingestion job response payload."""
    payload: dict[str, typ.Any] = {
        "id": str(job.id),
        "series_profile_id": str(job.series_profile_id),
        "target_episode_id": _optional_uuid_str(job.target_episode_id),
        "status": job.status.value,
        "intake_state": job.intake_state.value,
        "requested_at": job.requested_at.isoformat(),
        "started_at": None if job.started_at is None else job.started_at.isoformat(),
        "completed_at": (
            None if job.completed_at is None else job.completed_at.isoformat()
        ),
        "error_message": job.error_message,
        "created_at": job.created_at.isoformat(),
        "updated_at": job.updated_at.isoformat(),
    }
    if next_poll_after_seconds is not None:
        payload["next_poll_after_seconds"] = next_poll_after_seconds
    return payload


def serialize_ingestion_job_source(
    source: IngestionJobSource,
) -> dict[str, typ.Any]:
    """Serialize an intake source-attachment response payload."""
    return {
        "id": str(source.id),
        "ingestion_job_id": str(source.ingestion_job_id),
        "type": source.attachment_kind.value,
        "upload_id": _optional_uuid_str(source.upload_id),
        "source_uri": source.source_uri,
        "source_type": source.source_type,
        "weight": source.weight,
        "metadata": source.metadata,
        "created_at": source.created_at.isoformat(),
    }
