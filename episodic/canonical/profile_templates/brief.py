"""Structured-brief assembly entry point.

Orchestrates loading, validation, and serialisation of series profiles,
episode templates, and reference documents into a single brief payload.
Delegates to three private submodules:

- ``_brief_serializers`` — pure data-shaping transforms; no I/O.
- ``_brief_loaders`` — bulk entity loading, binding serialisation, and
  template-item resolution.
- ``_brief_reference_documents`` — episode-aware and legacy
  reference-document resolution strategies.

The sole public export is ``build_series_brief``.
"""

import typing as typ
from itertools import starmap

from ._brief_loaders import _load_template_items_for_brief
from ._brief_reference_documents import _load_reference_documents_for_brief
from ._brief_serializers import (
    _serialize_profile_for_brief,
    _serialize_template_for_brief,
)
from .services import get_entity_with_revision

if typ.TYPE_CHECKING:
    import uuid

    from episodic.canonical.domain import JsonMapping, SeriesProfile
    from episodic.canonical.unit_of_work_protocols import CanonicalUnitOfWork


async def build_series_brief(
    uow: CanonicalUnitOfWork,
    *,
    profile_id: uuid.UUID,
    template_id: uuid.UUID | None,
    episode_id: uuid.UUID | None = None,
) -> JsonMapping:
    """Build a structured brief payload for downstream generators.

    Parameters
    ----------
    uow : CanonicalUnitOfWork
        Unit-of-work instance used to load profile and template state.
    profile_id : uuid.UUID
        Identifier of the series profile to include in the brief.
    template_id : uuid.UUID | None
        Optional episode-template identifier. When provided, only that template
        is included. When ``None``, all templates for ``profile_id`` are
        included.
    episode_id : uuid.UUID | None
        Optional canonical-episode identifier used to resolve
        ``effective_from_episode_id`` precedence for series-level reference
        bindings.

    Returns
    -------
    JsonMapping
        Mapping with keys:
        ``series_profile`` (``dict[str, object]``) and
        ``episode_templates`` (``list[dict[str, object]]``), and
        ``reference_documents`` (``list[dict[str, object]]``), where entries
        contain serialized entity fields and revision metadata expected by
        downstream generation flows.

    Raises
    ------
    EntityNotFoundError
        Raised when the profile/template does not exist, or when a selected
        template does not belong to the requested profile.
    ValueError
        Raised when an unsupported entity kind is passed to delegated generic
        loaders.
    """
    profile_obj, profile_revision = await get_entity_with_revision(
        uow,
        entity_id=profile_id,
        kind="series_profile",
    )
    profile = typ.cast("SeriesProfile", profile_obj)
    template_items = await _load_template_items_for_brief(
        uow,
        profile_id=profile.id,
        template_id=template_id,
    )
    reference_documents = await _load_reference_documents_for_brief(
        uow,
        profile_id=profile.id,
        template_items=template_items,
        episode_id=episode_id,
    )

    return {
        "series_profile": _serialize_profile_for_brief(profile, profile_revision),
        "episode_templates": list(
            starmap(_serialize_template_for_brief, template_items)
        ),
        "reference_documents": reference_documents,
    }
