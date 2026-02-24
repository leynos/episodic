"""Canonical entities and profile/template service entry points.

This package exposes the canonical domain models together with ingestion and
profile/template orchestration APIs used by adapters.

Examples
--------
Use the exported service functions from application code:

>>> profile, _ = await create_series_profile(uow, data=data, audit=audit)
>>> template, _ = await create_episode_template(
...     uow, series_profile_id=profile.id, data=template_data
... )
>>> history = await list_history(uow, parent_id=profile.id, kind="series_profile")
>>> episodes = await ingest_sources(
...     request, extractor=extractor, deduplicator=deduplicator
... )
"""

from __future__ import annotations

from .domain import (
    ApprovalEvent,
    ApprovalState,
    CanonicalEpisode,
    EpisodeStatus,
    EpisodeTemplate,
    EpisodeTemplateHistoryEntry,
    IngestionJob,
    IngestionRequest,
    IngestionStatus,
    SeriesProfile,
    SeriesProfileHistoryEntry,
    SourceDocument,
    SourceDocumentInput,
    TeiHeader,
)
from .ingestion import (
    ConflictOutcome,
    MultiSourceRequest,
    NormalisedSource,
    RawSourceInput,
    WeightingResult,
)
from .ingestion_service import IngestionPipeline, ingest_multi_source
from .profile_templates import (
    EntityKind,
    EntityNotFoundError,
    RevisionConflictError,
    create_episode_template,
    create_series_profile,
    get_entity_with_revision,
    list_entities_with_revisions,
    list_history,
    update_episode_template,
    update_series_profile,
)

# isort: split
from .briefs import build_series_brief
from .services import ingest_sources

__all__: list[str] = [
    "ApprovalEvent",
    "ApprovalState",
    "CanonicalEpisode",
    "ConflictOutcome",
    "EntityKind",
    "EntityNotFoundError",
    "EpisodeStatus",
    "EpisodeTemplate",
    "EpisodeTemplateHistoryEntry",
    "IngestionJob",
    "IngestionPipeline",
    "IngestionRequest",
    "IngestionStatus",
    "MultiSourceRequest",
    "NormalisedSource",
    "RawSourceInput",
    "RevisionConflictError",
    "SeriesProfile",
    "SeriesProfileHistoryEntry",
    "SourceDocument",
    "SourceDocumentInput",
    "TeiHeader",
    "WeightingResult",
    "build_series_brief",
    "create_episode_template",
    "create_series_profile",
    "get_entity_with_revision",
    "ingest_multi_source",
    "ingest_sources",
    "list_entities_with_revisions",
    "list_history",
    "update_episode_template",
    "update_series_profile",
]
