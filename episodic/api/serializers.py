"""Response serializers for Falcon profile and template endpoints."""

import typing as typ
import uuid  # noqa: TC003

if typ.TYPE_CHECKING:
    from episodic.canonical.domain import (
        EpisodeTemplate,
        EpisodeTemplateHistoryEntry,
        ReferenceBinding,
        ReferenceDocument,
        ReferenceDocumentRevision,
        SeriesProfile,
        SeriesProfileHistoryEntry,
    )


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
