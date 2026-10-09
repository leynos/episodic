"""Unit-of-work implementation for canonical persistence.

This module defines the async unit-of-work used by canonical content services
to coordinate repository access and transactional boundaries.

Examples
--------
Commit work in a single unit-of-work:

>>> async with SqlAlchemyUnitOfWork(session_factory) as uow:
...     await uow.episodes.add(episode)
...     await uow.commit()
"""

import collections.abc as cabc  # ruff: ignore[typing-only-standard-library-import] - autospec resolves annotations
import dataclasses as dc
import typing as typ
from types import TracebackType  # ruff: ignore[typing-only-standard-library-import] - autospec resolves annotations

from sqlalchemy.ext.asyncio import (
    AsyncSession,  # ruff: ignore[typing-only-third-party-import] - autospec resolves annotations
)

from episodic.canonical.unit_of_work_protocols import CanonicalUnitOfWork
from episodic.cost.storage import SqlAlchemyCostLedgerStore
from episodic.logging import get_logger

if typ.TYPE_CHECKING:
    from episodic.observability import MetricsPort, MonotonicClockPort, TracerPort

from .episode_repository import SqlAlchemyEpisodeRepository
from .generation_run_storage_runtime import (  # ruff: ignore[typing-only-first-party-import] - autospec resolves annotations
    GenerationRunStorageRuntime,
)
from .generation_runs import SqlAlchemyGenerationRunStore
from .ingestion_job_repositories import SqlAlchemyIngestionJobRepository
from .repositories import (
    SqlAlchemyApprovalEventRepository,
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
    source_intake_storage_runtime,
)
from .workflow_checkpoints import SqlAlchemyWorkflowCheckpointStore

logger = get_logger(__name__)


@dc.dataclass(frozen=True, slots=True)
class UnitOfWorkRuntime:
    """Runtime collaborators used by unit-of-work storage adapters.

    Attributes
    ----------
    metrics : MetricsPort | None
        Optional metrics sink forwarded to storage adapters.
    monotonic_clock : MonotonicClockPort | None
        Optional monotonic clock forwarded to storage adapters.
    tracer : TracerPort | None
        Optional tracing sink forwarded to cost storage.
    generation_run_runtime : GenerationRunStorageRuntime | None
        Optional generation-run storage providers.
    """

    metrics: MetricsPort | None = None
    monotonic_clock: MonotonicClockPort | None = None
    tracer: TracerPort | None = None
    generation_run_runtime: GenerationRunStorageRuntime | None = None


class SqlAlchemyUnitOfWork(CanonicalUnitOfWork):
    """Async unit-of-work backed by SQLAlchemy sessions.

    Parameters
    ----------
    session_factory : collections.abc.Callable[[], AsyncSession]
        Factory that produces new async sessions for the unit-of-work scope.
    runtime : UnitOfWorkRuntime | None, optional
        Metrics, monotonic-clock, tracing, and generation-run storage
        collaborators forwarded to the storage adapters. Defaults to the
        adapters' canonical implementations.

    Attributes
    ----------
    series_profiles : SqlAlchemySeriesProfileRepository
        Repository for series profile persistence.
    tei_headers : SqlAlchemyTeiHeaderRepository
        Repository for TEI header persistence.
    episodes : SqlAlchemyEpisodeRepository
        Repository for canonical episode persistence.
    ingestion_jobs : SqlAlchemyIngestionJobRepository
        Repository for ingestion job persistence.
    source_documents : SqlAlchemySourceDocumentRepository
        Repository for source document persistence.
    approval_events : SqlAlchemyApprovalEventRepository
        Repository for approval event persistence.
    episode_templates : SqlAlchemyEpisodeTemplateRepository
        Repository for episode template persistence.
    series_profile_history : SqlAlchemySeriesProfileHistoryRepository
        Repository for series profile change history.
    episode_template_history : SqlAlchemyEpisodeTemplateHistoryRepository
        Repository for episode template change history.
    reference_documents : SqlAlchemyReferenceDocumentRepository
        Repository for reusable reference document persistence.
    reference_document_revisions : SqlAlchemyReferenceDocumentRevisionRepository
        Repository for immutable reusable reference document revisions.
    reference_bindings : SqlAlchemyReferenceBindingRepository
        Repository for reusable reference binding persistence.
    generation_runs : SqlAlchemyGenerationRunStore
        Repository and event log for durable generation runs.
    cost_ledger : SqlAlchemyCostLedgerStore
        Cost ledger adapter bound to the same session.
    """

    def __init__(
        self,
        session_factory: cabc.Callable[[], AsyncSession],
        *,
        runtime: UnitOfWorkRuntime | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._runtime = UnitOfWorkRuntime() if runtime is None else runtime
        self._session: AsyncSession | None = None

    async def __aenter__(self) -> SqlAlchemyUnitOfWork:
        """Open a unit-of-work session.

        Returns
        -------
        SqlAlchemyUnitOfWork
            The active unit-of-work instance.
        """
        self._session = self._session_factory()
        self.series_profiles = SqlAlchemySeriesProfileRepository(self._session)
        self.tei_headers = SqlAlchemyTeiHeaderRepository(self._session)
        self.episodes = SqlAlchemyEpisodeRepository(self._session)
        self.ingestion_jobs = SqlAlchemyIngestionJobRepository(self._session)
        self.source_documents = SqlAlchemySourceDocumentRepository(self._session)
        self.approval_events = SqlAlchemyApprovalEventRepository(self._session)
        self.episode_templates = SqlAlchemyEpisodeTemplateRepository(self._session)
        self.series_profile_history = SqlAlchemySeriesProfileHistoryRepository(
            self._session
        )
        self.episode_template_history = SqlAlchemyEpisodeTemplateHistoryRepository(
            self._session
        )
        self.reference_documents = SqlAlchemyReferenceDocumentRepository(self._session)
        self.reference_document_revisions = (
            SqlAlchemyReferenceDocumentRevisionRepository(self._session)
        )
        self.reference_bindings = SqlAlchemyReferenceBindingRepository(self._session)
        self.uploads = SqlAlchemyUploadRepository(self._session)
        self.ingestion_job_sources = SqlAlchemyIngestionJobSourceRepository(
            self._session
        )
        self.idempotency = SqlAlchemyIdempotencyStore(
            self._session,
            runtime=source_intake_storage_runtime(
                None,
                metrics=self._runtime.metrics,
                monotonic_clock=self._runtime.monotonic_clock,
            ),
        )
        self.generation_runs = SqlAlchemyGenerationRunStore(
            self._session,
            runtime=self._runtime.generation_run_runtime,
        )
        self.cost_ledger = SqlAlchemyCostLedgerStore(
            self._session,
            metrics=self._runtime.metrics,
            tracer=self._runtime.tracer,
            clock=self._runtime.monotonic_clock,
        )
        self.workflow_checkpoints = SqlAlchemyWorkflowCheckpointStore(
            self._session,
            metrics=self._runtime.metrics,
            clock=self._runtime.monotonic_clock,
        )
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Close the unit-of-work session.

        Parameters
        ----------
        exc_type : type[BaseException] | None
            Exception type raised within the context, if any.
        exc : BaseException | None
            Exception instance raised within the context, if any.
        traceback : TracebackType | None
            Traceback for the raised exception, if any.
        """
        if self._session is None:
            return
        try:
            if exc is not None:
                await self._session.rollback()
        finally:
            await self._session.close()

    def _require_session(self) -> AsyncSession:
        """Return the active session or raise when missing."""
        if self._session is None:
            msg = "Session not initialized for unit of work."
            raise RuntimeError(msg)
        return self._session

    async def _apply_session_action(self, action: str) -> None:
        """Apply a named action on the active session."""
        session = self._require_session()
        await getattr(session, action)()

    async def commit(self) -> None:
        """Commit the current unit-of-work transaction.

        Raises
        ------
        RuntimeError
            If no unit-of-work session is active.
        """  # ruff: ignore[docstring-extraneous-exception]  # Documents an exception propagated by the helper.
        await self._apply_session_action("commit")
        logger.info("Committed canonical unit of work.")

    async def flush(self) -> None:
        """Flush pending unit-of-work changes."""
        await self._require_session().flush()

    async def rollback(self) -> None:
        """Roll back the current unit-of-work session."""
        session = self._require_session()
        await session.rollback()
