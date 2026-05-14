"""Compatibility re-exports for canonical SQLAlchemy ORM models.

Alembic and repository callers import this module as the complete declarative
model surface.  The implementations live in focused modules to keep each file
below the project line-count limit.
"""

from .entity_models import (
    ApprovalEventRecord,
    EpisodeRecord,
    IngestionJobRecord,
    SourceDocumentRecord,
    TeiHeaderRecord,
)
from .history_models import EpisodeTemplateHistoryRecord, SeriesProfileHistoryRecord
from .models_base import (
    APPROVAL_STATE,
    EPISODE_STATUS,
    INGESTION_STATUS,
    REFERENCE_BINDING_TARGET_KIND,
    REFERENCE_DOCUMENT_KIND,
    REFERENCE_DOCUMENT_LIFECYCLE_STATE,
    WORKFLOW_CHECKPOINT_STATUS,
    Base,
)
from .profile_models import EpisodeTemplateRecord, SeriesProfileRecord
from .reference_models import (
    ReferenceBindingRecord,
    ReferenceDocumentRecord,
    ReferenceDocumentRevisionRecord,
)
from .workflow_checkpoint_models import WorkflowCheckpointRecord

__all__ = (
    "APPROVAL_STATE",
    "EPISODE_STATUS",
    "INGESTION_STATUS",
    "REFERENCE_BINDING_TARGET_KIND",
    "REFERENCE_DOCUMENT_KIND",
    "REFERENCE_DOCUMENT_LIFECYCLE_STATE",
    "WORKFLOW_CHECKPOINT_STATUS",
    "ApprovalEventRecord",
    "Base",
    "EpisodeRecord",
    "EpisodeTemplateHistoryRecord",
    "EpisodeTemplateRecord",
    "IngestionJobRecord",
    "ReferenceBindingRecord",
    "ReferenceDocumentRecord",
    "ReferenceDocumentRevisionRecord",
    "SeriesProfileHistoryRecord",
    "SeriesProfileRecord",
    "SourceDocumentRecord",
    "TeiHeaderRecord",
    "WorkflowCheckpointRecord",
)
