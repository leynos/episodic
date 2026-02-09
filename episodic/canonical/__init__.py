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
from .services import ingest_sources

__all__ = [
    "ApprovalEvent",
    "ApprovalState",
    "CanonicalEpisode",
    "EpisodeStatus",
    "IngestionJob",
    "IngestionRequest",
    "IngestionStatus",
    "SeriesProfile",
    "SourceDocument",
    "SourceDocumentInput",
    "TeiHeader",
    "ingest_sources",
]
