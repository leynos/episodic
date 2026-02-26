"""Public services for profile/template lifecycle operations.

This package exposes canonical application services used by API/resource
adapters to create, update, retrieve, and list profiles/templates with revision
metadata. Most functions return ``(entity, revision)`` pairs or history lists
and raise typed domain errors for missing entities or revision conflicts.

Examples
--------
>>> profile, revision = await create_series_profile(uow, data=data, audit=audit)
>>> template, rev = await get_episode_template(uow, template_id=template_id)
"""

from ._generic import (
    get_entity_with_revision,
    list_entities_with_revisions,
    list_history,
)
from ._typed import (
    create_episode_template,
    create_series_profile,
    get_episode_template,
    get_series_profile,
    list_episode_template_history,
    list_episode_templates,
    list_series_profile_history,
    list_series_profiles,
    update_episode_template,
    update_series_profile,
)

__all__: tuple[str, ...] = (
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
)
