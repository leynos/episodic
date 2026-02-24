"""Structured-brief assembly helpers for series profiles and templates."""

from __future__ import annotations

import typing as typ
from itertools import starmap

from episodic.canonical.profile_templates import (
    EntityNotFoundError,
    get_entity_with_revision,
    list_entities_with_revisions,
)

if typ.TYPE_CHECKING:
    import uuid

    from .domain import EpisodeTemplate, JsonMapping, SeriesProfile
    from .ports import CanonicalUnitOfWork


def _serialize_profile_for_brief(
    profile: SeriesProfile,
    revision: int,
) -> JsonMapping:
    """Serialize profile with revision for structured brief payloads."""
    return {
        "id": str(profile.id),
        "slug": profile.slug,
        "title": profile.title,
        "description": profile.description,
        "configuration": profile.configuration,
        "revision": revision,
        "updated_at": profile.updated_at.isoformat(),
    }


def _serialize_template_for_brief(
    template: EpisodeTemplate,
    revision: int,
) -> JsonMapping:
    """Serialize episode template with revision for structured brief payloads."""
    return {
        "id": str(template.id),
        "series_profile_id": str(template.series_profile_id),
        "slug": template.slug,
        "title": template.title,
        "description": template.description,
        "structure": template.structure,
        "revision": revision,
        "updated_at": template.updated_at.isoformat(),
    }


async def _load_template_items_for_brief(
    uow: CanonicalUnitOfWork,
    *,
    profile_id: uuid.UUID,
    template_id: uuid.UUID | None,
) -> list[tuple[EpisodeTemplate, int]]:
    """Load template and revision pairs for structured brief rendering."""
    if template_id is None:
        items = await list_entities_with_revisions(
            uow,
            kind="episode_template",
            series_profile_id=profile_id,
        )
        return [
            (typ.cast("EpisodeTemplate", template), revision)
            for template, revision in items
        ]

    template_obj, template_revision = await get_entity_with_revision(
        uow,
        entity_id=template_id,
        kind="episode_template",
    )
    template = typ.cast("EpisodeTemplate", template_obj)
    if template.series_profile_id != profile_id:
        msg = (
            f"Episode template {template.id} does not belong to "
            f"series profile {profile_id}."
        )
        raise EntityNotFoundError(msg)
    return [(template, template_revision)]


async def build_series_brief(
    uow: CanonicalUnitOfWork,
    *,
    profile_id: uuid.UUID,
    template_id: uuid.UUID | None,
) -> JsonMapping:
    """Build a structured brief payload for downstream generators.

    Parameters
    ----------
    uow : CanonicalUnitOfWork
        Active unit of work providing repository access.
    profile_id : uuid.UUID
        Identifier of the series profile to include in the brief.
    template_id : uuid.UUID | None
        Optional template identifier to scope the brief to one template.

    Returns
    -------
    JsonMapping
        Structured payload containing profile and template data with revisions.

    Raises
    ------
    EntityNotFoundError
        Raised when the profile or requested template does not exist, or when
        the template does not belong to the profile.
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

    return {
        "series_profile": _serialize_profile_for_brief(profile, profile_revision),
        "episode_templates": list(
            starmap(_serialize_template_for_brief, template_items)
        ),
    }
