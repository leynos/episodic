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
- Reusable reference resources:
  ``ReferenceDocumentsResource``, ``ReferenceDocumentResource``,
  ``ReferenceDocumentRevisionsResource``,
  ``ReferenceDocumentRevisionResource``, ``ReferenceBindingsResource``,
  ``ReferenceBindingResource``, ``ResolvedBindingsResource``
- Source-intake resources:
  ``UploadsResource``, ``UploadResource``, ``IngestionJobsResource``,
  ``IngestionJobResource``, ``IngestionJobSourcesResource``
- Health resources:
  ``HealthLiveResource``, ``HealthReadyResource``

Examples
--------
>>> from episodic.api.resources import SeriesProfilesResource, EpisodeTemplatesResource
>>> api.add_route("/profiles", SeriesProfilesResource(uow_factory))
>>> api.add_route("/templates", EpisodeTemplatesResource(uow_factory))
"""

from .base import _GetHistoryResourceBase, _GetResourceBase
from .episode_tei import EpisodeTeiResource
from .episode_templates import (
    EpisodeTemplateHistoryResource,
    EpisodeTemplateResource,
    EpisodeTemplatesResource,
)
from .generation_runs import (
    GenerationRunEventsResource,
    GenerationRunResource,
    GenerationRunsResource,
)
from .health import HealthLiveResource, HealthReadyResource
from .reference_bindings import ReferenceBindingResource, ReferenceBindingsResource
from .reference_documents import (
    ReferenceDocumentResource,
    ReferenceDocumentRevisionResource,
    ReferenceDocumentRevisionsResource,
    ReferenceDocumentsResource,
)
from .resolved_bindings import ResolvedBindingsResource
from .series_profiles import (
    SeriesProfileBriefResource,
    SeriesProfileHistoryResource,
    SeriesProfileResource,
    SeriesProfilesResource,
)
from .source_intake import (
    IngestionJobResource,
    IngestionJobSourcesResource,
    IngestionJobsResource,
    UploadResource,
    UploadsResource,
)

__all__ = [
    "EpisodeTeiResource",
    "EpisodeTemplateHistoryResource",
    "EpisodeTemplateResource",
    "EpisodeTemplatesResource",
    "GenerationRunEventsResource",
    "GenerationRunResource",
    "GenerationRunsResource",
    "HealthLiveResource",
    "HealthReadyResource",
    "IngestionJobResource",
    "IngestionJobSourcesResource",
    "IngestionJobsResource",
    "ReferenceBindingResource",
    "ReferenceBindingsResource",
    "ReferenceDocumentResource",
    "ReferenceDocumentRevisionResource",
    "ReferenceDocumentRevisionsResource",
    "ReferenceDocumentsResource",
    "ResolvedBindingsResource",
    "SeriesProfileBriefResource",
    "SeriesProfileHistoryResource",
    "SeriesProfileResource",
    "SeriesProfilesResource",
    "UploadResource",
    "UploadsResource",
    "_GetHistoryResourceBase",
    "_GetResourceBase",
]
