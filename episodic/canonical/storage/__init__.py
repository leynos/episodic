"""SQLAlchemy persistence adapters for canonical content.

This package provides the SQLAlchemy models, repositories, and unit-of-work
implementation used by canonical content services. It keeps persistence logic
isolated from the domain layer while exposing a clean port-oriented API.

Examples
--------
Use the unit-of-work to fetch a canonical episode:

>>> async with SqlAlchemyUnitOfWork(session_factory) as uow:
...     episode = await uow.episodes.get(episode_id)
"""

from .filesystem_object_store import FilesystemObjectStore
from .ingestion_job_repositories import SqlAlchemyIngestionJobRepository
from .migration_check import detect_schema_drift
from .models import (
    ApprovalEventRecord,
    Base,
    EpisodeRecord,
    EpisodeTemplateHistoryRecord,
    EpisodeTemplateRecord,
    IdempotencyRecordModel,
    IngestionJobRecord,
    IngestionJobSourceRecord,
    ReferenceBindingRecord,
    ReferenceDocumentRecord,
    ReferenceDocumentRevisionRecord,
    SeriesProfileHistoryRecord,
    SeriesProfileRecord,
    SourceDocumentRecord,
    TeiHeaderRecord,
    UploadRecord,
    WorkflowCheckpointRecord,
)
from .repositories import (
    SqlAlchemyApprovalEventRepository,
    SqlAlchemyEpisodeRepository,
    SqlAlchemyEpisodeTemplateHistoryRepository,
    SqlAlchemyEpisodeTemplateRepository,
    SqlAlchemyReferenceBindingRepository,
    SqlAlchemyReferenceDocumentRepository,
    SqlAlchemyReferenceDocumentRevisionRepository,
    SqlAlchemySeriesProfileHistoryRepository,
    SqlAlchemySeriesProfileRepository,
    SqlAlchemySourceDocumentRepository,
    SqlAlchemyTeiHeaderRepository,
)
from .source_intake_repositories import (
    SqlAlchemyIdempotencyStore,
    SqlAlchemyIngestionJobSourceRepository,
    SqlAlchemyUploadRepository,
)
from .uow import SqlAlchemyUnitOfWork
from .workflow_checkpoints import SqlAlchemyWorkflowCheckpointStore

__all__ = (
    "ApprovalEventRecord",
    "Base",
    "EpisodeRecord",
    "EpisodeTemplateHistoryRecord",
    "EpisodeTemplateRecord",
    "FilesystemObjectStore",
    "IdempotencyRecordModel",
    "IngestionJobRecord",
    "IngestionJobSourceRecord",
    "ReferenceBindingRecord",
    "ReferenceDocumentRecord",
    "ReferenceDocumentRevisionRecord",
    "SeriesProfileHistoryRecord",
    "SeriesProfileRecord",
    "SourceDocumentRecord",
    "SqlAlchemyApprovalEventRepository",
    "SqlAlchemyEpisodeRepository",
    "SqlAlchemyEpisodeTemplateHistoryRepository",
    "SqlAlchemyEpisodeTemplateRepository",
    "SqlAlchemyIdempotencyStore",
    "SqlAlchemyIngestionJobRepository",
    "SqlAlchemyIngestionJobSourceRepository",
    "SqlAlchemyReferenceBindingRepository",
    "SqlAlchemyReferenceDocumentRepository",
    "SqlAlchemyReferenceDocumentRevisionRepository",
    "SqlAlchemySeriesProfileHistoryRepository",
    "SqlAlchemySeriesProfileRepository",
    "SqlAlchemySourceDocumentRepository",
    "SqlAlchemyTeiHeaderRepository",
    "SqlAlchemyUnitOfWork",
    "SqlAlchemyUploadRepository",
    "SqlAlchemyWorkflowCheckpointStore",
    "TeiHeaderRecord",
    "UploadRecord",
    "WorkflowCheckpointRecord",
    "detect_schema_drift",
)
