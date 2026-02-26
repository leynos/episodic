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

from .migration_check import detect_schema_drift
from .models import (
    ApprovalEventRecord,
    Base,
    EpisodeRecord,
    EpisodeTemplateHistoryRecord,
    EpisodeTemplateRecord,
    IngestionJobRecord,
    SeriesProfileHistoryRecord,
    SeriesProfileRecord,
    SourceDocumentRecord,
    TeiHeaderRecord,
)
from .repositories import (
    SqlAlchemyApprovalEventRepository,
    SqlAlchemyEpisodeRepository,
    SqlAlchemyEpisodeTemplateHistoryRepository,
    SqlAlchemyEpisodeTemplateRepository,
    SqlAlchemyIngestionJobRepository,
    SqlAlchemySeriesProfileHistoryRepository,
    SqlAlchemySeriesProfileRepository,
    SqlAlchemySourceDocumentRepository,
    SqlAlchemyTeiHeaderRepository,
)
from .uow import SqlAlchemyUnitOfWork

__all__ = (
    "ApprovalEventRecord",
    "Base",
    "EpisodeRecord",
    "EpisodeTemplateHistoryRecord",
    "EpisodeTemplateRecord",
    "IngestionJobRecord",
    "SeriesProfileHistoryRecord",
    "SeriesProfileRecord",
    "SourceDocumentRecord",
    "SqlAlchemyApprovalEventRepository",
    "SqlAlchemyEpisodeRepository",
    "SqlAlchemyEpisodeTemplateHistoryRepository",
    "SqlAlchemyEpisodeTemplateRepository",
    "SqlAlchemyIngestionJobRepository",
    "SqlAlchemySeriesProfileHistoryRepository",
    "SqlAlchemySeriesProfileRepository",
    "SqlAlchemySourceDocumentRepository",
    "SqlAlchemyTeiHeaderRepository",
    "SqlAlchemyUnitOfWork",
    "TeiHeaderRecord",
    "detect_schema_drift",
)
