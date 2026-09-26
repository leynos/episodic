"""Project resolved reference-document bindings into draft presenter profiles.

``project_presenter_profiles`` filters resolved host and guest
reference-document bindings down to the presenter kinds, then builds the
immutable ``DraftPresenterProfile`` records consumed by
``DraftScriptGenerator``. It does not open, commit, or dispose persistence
sessions itself.
"""

import json
import typing as typ

from episodic.canonical.domain import ReferenceDocumentKind
from episodic.generation.draft_script import DraftPresenterProfile

if typ.TYPE_CHECKING:
    import collections.abc as cabc

    from episodic.canonical.reference_documents.resolution import ResolvedBinding


def project_presenter_profiles(
    resolved_bindings: list[ResolvedBinding],
) -> tuple[DraftPresenterProfile, ...]:
    """Project resolved host and guest revisions into draft input records."""
    presenter_kinds = {
        ReferenceDocumentKind.HOST_PROFILE,
        ReferenceDocumentKind.GUEST_PROFILE,
    }
    profiles: list[DraftPresenterProfile] = []
    for resolved in resolved_bindings:
        if resolved.document.kind not in presenter_kinds:
            continue
        content = resolved.revision.content
        metadata = resolved.document.metadata
        display_name = _first_string(content, "display_name", "name", "title")
        display_name = display_name or _first_string(
            metadata, "display_name", "name", "title"
        )
        source_content = _first_string(
            content,
            "source_content",
            "profile",
            "bio",
            "biography",
            "summary",
            "content",
            "text",
        )
        profiles.append(
            DraftPresenterProfile(
                display_name=display_name or str(resolved.document.id),
                role=resolved.document.kind.value.removesuffix("_profile"),
                source_content=source_content or json.dumps(content, sort_keys=True),
            )
        )
    return tuple(profiles)


def _first_string(values: cabc.Mapping[str, object], *keys: str) -> str | None:
    """Return the first non-empty string from the requested mapping keys."""
    for key in keys:
        value = values.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None
