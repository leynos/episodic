"""Canonical content domain and persistence interfaces."""

from __future__ import annotations

from .domain import (
    ApprovalEvent,
    ApprovalState,
    CanonicalEpisode,
    EpisodeStatus,
    IngestionJob,
    IngestionRequest,
    IngestionStatus,
    SeriesProfile,
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
from .services import ingest_sources

__all__ = [
    "ApprovalEvent",
    "ApprovalState",
    "CanonicalEpisode",
    "ConflictOutcome",
    "EpisodeStatus",
    "IngestionJob",
    "IngestionPipeline",
    "IngestionRequest",
    "IngestionStatus",
    "MultiSourceRequest",
    "NormalisedSource",
    "RawSourceInput",
    "SeriesProfile",
    "SourceDocument",
    "SourceDocumentInput",
    "TeiHeader",
    "WeightingResult",
    "ingest_multi_source",
    "ingest_sources",
]
