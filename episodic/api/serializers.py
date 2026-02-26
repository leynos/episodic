"""Response serializers for Falcon profile and template endpoints."""

import typing as typ

if typ.TYPE_CHECKING:
    from episodic.canonical.domain import (
        EpisodeTemplate,
        EpisodeTemplateHistoryEntry,
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
