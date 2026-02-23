"""Canonical content domain and persistence interfaces."""

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
    build_series_brief,
    create_episode_template,
    create_series_profile,
    get_entity_with_revision,
    list_entities_with_revisions,
    list_history,
    update_episode_template,
    update_series_profile,
)
from .services import ingest_sources

__all__ = [
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
