"""Falcon resource adapters for canonical profile/template endpoints."""

from __future__ import annotations

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
