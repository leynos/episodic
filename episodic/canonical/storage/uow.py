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
from episodic.logging import log_event as _log_event

if typ.TYPE_CHECKING:
    from episodic.observability import (
        MetricsPort,
        MonotonicClockPort,
        TracerPort,
        ValueMetricsPort,
    )

from .episode_repository import SqlAlchemyEpisodeRepository
from .generation_run_port_adapter import SqlAlchemyGenerationRunPortAdapter
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
from .review_checkpoints import SqlAlchemyReviewCheckpointStore
from .session_write_tracker import SessionWriteTracker
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
    value_metrics : ValueMetricsPort | None
        Optional scalar-metrics sink, used by adapters that report gauges.
        `metrics` alone is insufficient: `MetricsPort` has no `observe_value`.
    """

    metrics: MetricsPort | None = None
    monotonic_clock: MonotonicClockPort | None = None
    tracer: TracerPort | None = None
    generation_run_runtime: GenerationRunStorageRuntime | None = None
    value_metrics: ValueMetricsPort | None = None


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
    generation_runs : SqlAlchemyGenerationRunPortAdapter
        Composite port for durable generation runs: the run repository, the
        append-only event log, and the review-checkpoint store, bound to the
        same session.
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
        self._writes: SessionWriteTracker | None = None

    async def __aenter__(self) -> SqlAlchemyUnitOfWork:
        """Open a unit-of-work session.

        Returns
        -------
        SqlAlchemyUnitOfWork
            The active unit-of-work instance.
        """
        self._session = self._session_factory()
        self._writes = SessionWriteTracker(self._session.sync_session)
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
        self.generation_runs = SqlAlchemyGenerationRunPortAdapter(
            SqlAlchemyGenerationRunStore(
                self._session,
                runtime=self._runtime.generation_run_runtime,
            ),
            SqlAlchemyReviewCheckpointStore(
                self._session,
                runtime=self._runtime.generation_run_runtime,
                metrics=self._runtime.value_metrics,
            ),
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

        Closing does **not** commit. Work left pending when the context exits
        cleanly is discarded silently, which is the most likely durability bug
        in a new slice and is invisible in a test that only checks the entity
        it already holds. The event below makes it greppable instead.

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
            elif self._has_pending_changes():
                # Emitted as a structured event, not a bare warning: the
                # canonical logger is a femtologging logger whose records do
                # not reach stdlib handlers, so a plain logger.warning() would
                # be invisible to caplog and therefore to any regression test.
                _log_event(
                    "warning",
                    "canonical_unit_of_work.closed_with_uncommitted_changes",
                    outcome="discarded",
                )
        finally:
            await self._session.close()

    def _has_pending_changes(self) -> bool:
        """Return whether the active session holds unsettled writes.

        Delegated to the tracker rather than read off ``Session.new`` and
        friends, which are emptied by every flush and never populated by a core
        ``UPDATE``. Consulting them here would make this check silent on
        exactly the writes it exists to catch.

        Returns
        -------
        bool
            Whether a write has been observed and not yet settled.
        """
        return self._writes is not None and self._writes.wrote

    def _mark_settled(self) -> None:
        """Clear tracked writes once the session's work has been settled."""
        if self._writes is not None:
            self._writes.mark_clean()

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
        self._mark_settled()
        logger.info("Committed canonical unit of work.")

    async def flush(self) -> None:
        """Flush pending unit-of-work changes."""
        await self._require_session().flush()

    async def rollback(self) -> None:
        """Roll back the current unit-of-work session."""
        session = self._require_session()
        await session.rollback()
        self._mark_settled()
