"""Falcon resources for canonical profile and template endpoints.

This package exposes route adapter classes that translate Falcon request/
response handling into calls to canonical profile/template services.

Utilities provided
------------------
- Shared read base classes: ``_GetResourceBase``, ``_GetHistoryResourceBase``
- Series profile resources:
  ``SeriesProfilesResource``, ``SeriesProfileResource``,
  ``SeriesProfileHistoryResource``, ``SeriesProfileBriefResource``
- Episode template resources:
  ``EpisodeTemplatesResource``, ``EpisodeTemplateResource``,
  ``EpisodeTemplateHistoryResource``

Examples
--------
>>> from episodic.api.resources import SeriesProfilesResource, EpisodeTemplatesResource
>>> api.add_route("/profiles", SeriesProfilesResource(uow_factory))
>>> api.add_route("/templates", EpisodeTemplatesResource(uow_factory))
"""

from .base import _GetHistoryResourceBase, _GetResourceBase
from .episode_templates import (
    EpisodeTemplateHistoryResource,
    EpisodeTemplateResource,
    EpisodeTemplatesResource,
)
from .series_profiles import (
    SeriesProfileBriefResource,
    SeriesProfileHistoryResource,
    SeriesProfileResource,
    SeriesProfilesResource,
)

__all__ = [
    "EpisodeTemplateHistoryResource",
    "EpisodeTemplateResource",
    "EpisodeTemplatesResource",
    "SeriesProfileBriefResource",
    "SeriesProfileHistoryResource",
    "SeriesProfileResource",
    "SeriesProfilesResource",
    "_GetHistoryResourceBase",
    "_GetResourceBase",
]
