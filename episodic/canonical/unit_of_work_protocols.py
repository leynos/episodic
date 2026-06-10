"""Unit-of-work protocol for canonical persistence."""

import typing as typ

if typ.TYPE_CHECKING:
    from types import TracebackType

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
    from .upload_protocols import (
        IdempotencyStore,
        IngestionJobSourceRepository,
        UploadRepository,
    )


@typ.runtime_checkable
class CanonicalUnitOfWork(typ.Protocol):
    """Unit-of-work boundary for canonical persistence."""

    series_profiles: SeriesProfileRepository
    tei_headers: TeiHeaderRepository
    episodes: EpisodeRepository
    ingestion_jobs: IngestionJobRepository
    source_documents: SourceDocumentRepository
    approval_events: ApprovalEventRepository
    episode_templates: EpisodeTemplateRepository
    series_profile_history: SeriesProfileHistoryRepository
    episode_template_history: EpisodeTemplateHistoryRepository
    reference_documents: ReferenceDocumentRepository
    reference_document_revisions: ReferenceDocumentRevisionRepository
    reference_bindings: ReferenceBindingRepository
    uploads: UploadRepository
    ingestion_job_sources: IngestionJobSourceRepository
    idempotency: IdempotencyStore

    async def __aenter__(self) -> CanonicalUnitOfWork:
        """Enter the unit-of-work context."""
        raise NotImplementedError

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Exit the unit-of-work context."""
        raise NotImplementedError

    async def commit(self) -> None:
        """Commit the current unit-of-work transaction."""
        raise NotImplementedError

    async def flush(self) -> None:
        """Flush pending changes without committing."""
        raise NotImplementedError

    async def rollback(self) -> None:
        """Roll back the current unit-of-work transaction."""
        raise NotImplementedError
