"""Compatibility re-exports for canonical persistence protocols."""

from .entity_protocols import (
    ApprovalEventRepository,
    EpisodeRepository,
    EpisodeTemplateRepository,
    IngestionJobRepository,
    SeriesProfileRepository,
    SourceDocumentRepository,
    TeiHeaderRepository,
)
from .history_protocols import (
    EpisodeTemplateHistoryRepository,
    SeriesProfileHistoryRepository,
)
from .reference_protocols import (
    ReferenceBindingRepository,
    ReferenceDocumentRepository,
    ReferenceDocumentRevisionRepository,
)
from .unit_of_work_protocols import CanonicalUnitOfWork

__all__ = [
    "ApprovalEventRepository",
    "CanonicalUnitOfWork",
    "EpisodeRepository",
    "EpisodeTemplateHistoryRepository",
    "EpisodeTemplateRepository",
    "IngestionJobRepository",
    "ReferenceBindingRepository",
    "ReferenceDocumentRepository",
    "ReferenceDocumentRevisionRepository",
    "SeriesProfileHistoryRepository",
    "SeriesProfileRepository",
    "SourceDocumentRepository",
    "TeiHeaderRepository",
]
