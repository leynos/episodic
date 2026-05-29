"""Serializers that shape entity data into structured-brief payloads.

These functions are pure data-shaping transforms to ``JsonMapping`` payloads
with no database dependencies.
"""

import typing as typ

if typ.TYPE_CHECKING:
    from episodic.canonical.domain import (
        EpisodeTemplate,
        JsonMapping,
        ReferenceBinding,
        ReferenceDocument,
        ReferenceDocumentRevision,
        SeriesProfile,
    )


def _serialize_profile_for_brief(
    profile: SeriesProfile,
    revision: int,
) -> JsonMapping:
    """Serialize profile with revision for structured brief payloads."""
    from .helpers import _profile_payload_fields

    return {
        **_profile_payload_fields(profile),
        "revision": revision,
        "updated_at": profile.updated_at.isoformat(),
    }


def _serialize_template_for_brief(
    template: EpisodeTemplate,
    revision: int,
) -> JsonMapping:
    """Serialize episode template with revision for structured brief payloads."""
    from .helpers import _template_payload_fields

    return {
        **_template_payload_fields(template),
        "revision": revision,
        "updated_at": template.updated_at.isoformat(),
    }


def _serialize_reference_document_for_brief(
    *,
    binding: ReferenceBinding,
    document: ReferenceDocument,
    revision: ReferenceDocumentRevision,
) -> JsonMapping:
    """Serialize a reference binding/document/revision triple."""
    return {
        "binding_id": str(binding.id),
        "document_id": str(document.id),
        "revision_id": str(revision.id),
        "kind": document.kind.value,
        "target_kind": binding.target_kind.value,
        "effective_from_episode_id": (
            None
            if binding.effective_from_episode_id is None
            else str(binding.effective_from_episode_id)
        ),
        "lifecycle_state": document.lifecycle_state.value,
        "metadata": document.metadata,
        "content": revision.content,
        "content_hash": revision.content_hash,
    }
