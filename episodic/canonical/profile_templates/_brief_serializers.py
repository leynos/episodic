"""Serialisers that shape entity data into structured-brief payloads.

These functions are pure data-shaping transforms to ``JsonMapping`` payloads
with no database dependencies. Consumed by ``_brief_loaders`` (via
``_serialize_bindings_for_owner``) and by ``_brief_reference_documents``
(via ``_serialize_reference_document_for_brief``). Not part of the public
package API; import only through the ``brief`` entry point.
"""

import typing as typ

from .helpers import _profile_payload_fields, _template_payload_fields

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
    effective_from = binding.effective_from_episode_id
    effective_from_episode_id = None if effective_from is None else str(effective_from)
    return {
        "binding_id": str(binding.id),
        "document_id": str(document.id),
        "revision_id": str(revision.id),
        "kind": document.kind.value,
        "target_kind": binding.target_kind.value,
        "effective_from_episode_id": effective_from_episode_id,
        "lifecycle_state": document.lifecycle_state.value,
        "metadata": document.metadata,
        "content": revision.content,
        "content_hash": revision.content_hash,
    }
