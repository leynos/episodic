"""Project resolved guest-profile bindings into generator prompt sources."""

import json
import typing as typ

from episodic.canonical.domain import ReferenceDocumentKind

if typ.TYPE_CHECKING:
    from episodic.canonical.reference_documents.resolution import ResolvedBinding
    from episodic.generation.guest_bios import GuestBioSource
else:
    GuestBioSource = object

type JsonMapping = dict[str, object]


def project_guest_bio_sources(
    resolved_bindings: list[ResolvedBinding],
) -> tuple[GuestBioSource, ...]:
    """Project guest-profile bindings into immutable prompt source records."""
    from episodic.generation.guest_bios import GuestBioSource

    sources: list[GuestBioSource] = []
    for resolved in resolved_bindings:
        if resolved.document.kind is not ReferenceDocumentKind.GUEST_PROFILE:
            continue
        revision_content = resolved.revision.content
        document_metadata = resolved.document.metadata
        display_name = _first_content_string(
            revision_content, "display_name", "name", "title"
        ) or _first_content_string(document_metadata, "display_name", "name", "title")
        source_content = _first_content_string(
            revision_content,
            "source_content",
            "profile",
            "bio",
            "biography",
            "summary",
            "content",
            "text",
        ) or _json_source_content(revision_content)
        sources.append(
            GuestBioSource(
                display_name=display_name or str(resolved.document.id),
                role=_first_content_string(revision_content, "role", "occupation")
                or _first_content_string(document_metadata, "role", "occupation"),
                reference_document_id=str(resolved.document.id),
                reference_document_revision_id=str(resolved.revision.id),
                source_content=source_content,
            )
        )
    return tuple(sources)


def _first_content_string(payload: JsonMapping, *field_names: str) -> str | None:
    """Return the first non-blank string from mapping fields."""
    for field_name in field_names:
        value = payload.get(field_name)
        if isinstance(value, str) and (normalized := value.strip()):
            return normalized
    return None


def _json_source_content(payload: JsonMapping) -> str:
    """Serialize structured reference content for source-grounded prompts."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))
