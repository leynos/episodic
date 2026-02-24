"""Public exports for ``episodic.canonical.profile_templates``.

This package groups canonical profile/template lifecycle APIs, shared request
types, and errors used by adapters and application services. Import from this
module when you need the stable public surface re-exported via ``__all__``.

Examples
--------
>>> from episodic.canonical.profile_templates import create_series_profile, list_history
>>> profile, revision = await create_series_profile(uow, data=data, audit=audit)
"""

from __future__ import annotations

from .brief import build_series_brief
from .services import (
    create_episode_template,
    create_series_profile,
    get_entity_with_revision,
    get_episode_template,
    get_series_profile,
    list_entities_with_revisions,
    list_episode_template_history,
    list_episode_templates,
    list_history,
    list_series_profile_history,
    list_series_profiles,
    update_episode_template,
    update_series_profile,
)
from .types import (
    AuditMetadata,
    EntityKind,
    EntityNotFoundError,
    EpisodeTemplateData,
    EpisodeTemplateUpdateFields,
    RevisionConflictError,
    SeriesProfileCreateData,
    SeriesProfileData,
    SeriesProfileUpdateFields,
    UpdateEpisodeTemplateRequest,
    UpdateSeriesProfileRequest,
)

__all__: list[str] = [
    "AuditMetadata",
    "EntityKind",
    "EntityNotFoundError",
    "EpisodeTemplateData",
    "EpisodeTemplateUpdateFields",
    "RevisionConflictError",
    "SeriesProfileCreateData",
    "SeriesProfileData",
    "SeriesProfileUpdateFields",
    "UpdateEpisodeTemplateRequest",
    "UpdateSeriesProfileRequest",
    "build_series_brief",
    "create_episode_template",
    "create_series_profile",
    "get_entity_with_revision",
    "get_episode_template",
    "get_series_profile",
    "list_entities_with_revisions",
    "list_episode_template_history",
    "list_episode_templates",
    "list_history",
    "list_series_profile_history",
    "list_series_profiles",
    "update_episode_template",
    "update_series_profile",
]
