"""Domain models for canonical content storage.

The concrete dataclasses and enumerations previously defined here now live in
focused ``domain_*`` sibling modules, grouped by cohesive responsibility
(lifecycle enums, shared validators, generation runs and checkpoints,
episodes, ingestion, reference documents, and profile/template metadata).
This module re-exports every public name so existing import paths continue
to resolve unchanged.
"""

from .domain_enums import (
    ApprovalState,
    CheckpointAction,
    CheckpointStatus,
    EpisodeStatus,
    GenerationRunStatus,
    IngestionStatus,
    IntakeState,
    JsonMapping,
    ReferenceBindingTargetKind,
    ReferenceDocumentKind,
    ReferenceDocumentLifecycleState,
    WorkflowCheckpointStatus,
)
from .domain_episodes import ApprovalEvent, CanonicalEpisode, EpisodeTeiUpdate
from .domain_generation import (
    Checkpoint,
    CheckpointResponse,
    GenerationEvent,
    GenerationRun,
)
from .domain_generation import (
    _validate_terminal_run_lifecycle as _validate_terminal_run_lifecycle,
)
from .domain_ingestion import (
    IngestionJob,
    IngestionJobListFilters,
    IngestionRequest,
    SourceDocument,
    SourceDocumentInput,
)
from .domain_reference_documents import (
    ReferenceBinding,
    ReferenceDocument,
    ReferenceDocumentRevision,
)
from .domain_templates import (
    EpisodeTemplate,
    EpisodeTemplateHistoryEntry,
    SeriesProfile,
    SeriesProfileHistoryEntry,
    TeiHeader,
)

__all__ = [
    "ApprovalEvent",
    "ApprovalState",
    "CanonicalEpisode",
    "Checkpoint",
    "CheckpointAction",
    "CheckpointResponse",
    "CheckpointStatus",
    "EpisodeStatus",
    "EpisodeTeiUpdate",
    "EpisodeTemplate",
    "EpisodeTemplateHistoryEntry",
    "GenerationEvent",
    "GenerationRun",
    "GenerationRunStatus",
    "IngestionJob",
    "IngestionJobListFilters",
    "IngestionRequest",
    "IngestionStatus",
    "IntakeState",
    "JsonMapping",
    "ReferenceBinding",
    "ReferenceBindingTargetKind",
    "ReferenceDocument",
    "ReferenceDocumentKind",
    "ReferenceDocumentLifecycleState",
    "ReferenceDocumentRevision",
    "SeriesProfile",
    "SeriesProfileHistoryEntry",
    "SourceDocument",
    "SourceDocumentInput",
    "TeiHeader",
    "WorkflowCheckpointStatus",
]
