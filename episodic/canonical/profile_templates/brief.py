"""Structured-brief assembly helpers for series profiles and templates.

Use this module when an adapter needs a single payload that combines one series
profile with either all of its episode templates or one selected template.
Helpers here fetch current entity revisions, enforce profile/template ownership
constraints, and return a JSON mapping without mutating persisted state.

Examples
--------
Build a structured brief for one profile and optional template filter:

>>> brief = await build_series_brief(uow, profile_id=profile_id, template_id=None)
>>> brief["episode_templates"]  # list[dict[str, object]]
"""

import typing as typ
from itertools import starmap

from .helpers import _profile_payload_fields, _template_payload_fields
from .services import get_entity_with_revision, list_entities_with_revisions
from .types import EntityNotFoundError

if typ.TYPE_CHECKING:
    import uuid

    from episodic.canonical.domain import EpisodeTemplate, JsonMapping, SeriesProfile
    from episodic.canonical.ports import CanonicalUnitOfWork


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
        raise EntityNotFoundError(msg, entity_id=str(template.id))
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
        Unit-of-work instance used to load profile and template state.
    profile_id : uuid.UUID
        Identifier of the series profile to include in the brief.
    template_id : uuid.UUID | None
        Optional episode-template identifier. When provided, only that template
        is included. When ``None``, all templates for ``profile_id`` are
        included.

    Returns
    -------
    JsonMapping
        Mapping with keys:
        ``series_profile`` (``dict[str, object]``) and
        ``episode_templates`` (``list[dict[str, object]]``), where each entry
        contains serialized entity fields and revision metadata expected by
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

    return {
        "series_profile": _serialize_profile_for_brief(profile, profile_revision),
        "episode_templates": list(
            starmap(_serialize_template_for_brief, template_items)
        ),
    }
