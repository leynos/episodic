"""Builders for canonical profile/template entities and history entries.

These builders produce plain domain objects (not persisted records) so storage
tests can construct parents and their history entries without duplicating the
field-by-field construction in each test module. Keeping them here avoids the
builders drifting apart as new history models or fields are added.
"""

import datetime as dt
import typing as typ
import uuid

from episodic.canonical.domain import (
    EpisodeTemplate,
    EpisodeTemplateHistoryEntry,
    SeriesProfile,
    SeriesProfileHistoryEntry,
)


def _now() -> dt.datetime:
    """Return a timezone-aware current timestamp."""
    return dt.datetime.now(dt.UTC)


def build_series_profile(profile_id: uuid.UUID | None = None) -> SeriesProfile:
    """Return a minimal series profile for history-focused tests."""
    resolved_id = profile_id if profile_id is not None else uuid.uuid4()
    now = _now()
    return SeriesProfile(
        id=resolved_id,
        slug=f"history-conflict-{resolved_id}",
        title="History Conflict",
        description=None,
        configuration={},
        guardrails={},
        created_at=now,
        updated_at=now,
    )


def build_episode_template(
    series_profile_id: uuid.UUID,
    template_id: uuid.UUID | None = None,
) -> EpisodeTemplate:
    """Return a minimal episode template owned by ``series_profile_id``."""
    resolved_id = template_id if template_id is not None else uuid.uuid4()
    now = _now()
    return EpisodeTemplate(
        id=resolved_id,
        series_profile_id=series_profile_id,
        slug=f"history-conflict-template-{resolved_id}",
        title="History Conflict Template",
        description=None,
        structure={"sections": []},
        guardrails={},
        created_at=now,
        updated_at=now,
    )


def build_history_entry(
    entry_cls: type,
    parent_field: str,
    parent_id: uuid.UUID,
    *,
    revision: int,
) -> typ.Any:  # noqa: ANN401  # builds heterogeneous history entry dataclasses
    """Build a history entry of ``entry_cls`` at ``revision``.

    ``parent_field`` is the keyword argument name that holds the parent entity
    identifier (for example ``"series_profile_id"``).
    """
    return entry_cls(
        id=uuid.uuid4(),
        **{parent_field: parent_id},
        revision=revision,
        actor="actor@example.com",
        note=f"Revision {revision}",
        snapshot={"revision": revision},
        created_at=_now(),
    )


def build_series_profile_history_entry(
    profile_id: uuid.UUID,
    *,
    revision: int,
) -> SeriesProfileHistoryEntry:
    """Build a series-profile history entry at ``revision``."""
    return build_history_entry(
        SeriesProfileHistoryEntry,
        "series_profile_id",
        profile_id,
        revision=revision,
    )


def build_episode_template_history_entry(
    template_id: uuid.UUID,
    *,
    revision: int,
) -> EpisodeTemplateHistoryEntry:
    """Build an episode-template history entry at ``revision``."""
    return build_history_entry(
        EpisodeTemplateHistoryEntry,
        "episode_template_id",
        template_id,
        revision=revision,
    )
