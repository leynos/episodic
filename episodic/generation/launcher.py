"""Schedule and execute bounded no-QA generation runs in the API process.

The public :class:`GenerationRunLauncher` port and
:class:`InProcessGenerationRunLauncher` service connect the generation-run API
resource to canonical run persistence. A launcher claims a
:class:`~episodic.canonical.domain.GenerationRun`, loads its episode, source
documents, and resolved presenter bindings through fresh
:class:`~episodic.canonical.unit_of_work_protocols.CanonicalUnitOfWork`
instances, then delegates draft creation to :class:`DraftScriptGenerator`.
It records ordered lifecycle events, persists the generated TEI through
``persist_draft_script``, records optional provider costs, and applies the
immutable ``GenerationRunStatusUpdate`` command for terminal state changes.

Admission is bounded before an asyncio task is allocated, and strong task
references support draining or cancellation. The launcher exposes metrics and
tracing ports, records cancellation as a terminal failure, and treats leases
as inspection and manual-recovery hooks rather than restart recovery. The
runtime shuts the launcher down before closing the provider and disposing the
database engine; request-scoped units of work must never be passed to a
background task.
"""

import asyncio
import dataclasses as dc
import datetime as dt
import typing as typ

from episodic.canonical.domain import GenerationRunStatus
from episodic.canonical.generation_persistence import (
    DraftScriptPersistenceRequest,
    persist_draft_script,
)
from episodic.canonical.generation_quality import QaStatus
from episodic.canonical.generation_run_errors import RunAlreadyTerminal, RunNotFound
from episodic.canonical.generation_run_ports import GenerationRunStatusUpdate
from episodic.canonical.reference_documents import resolve_bindings
from episodic.cost.ports import BillingPeriodKey
from episodic.cost.recorder import CostProviderOperation
from episodic.generation.launcher_support import (
    ClaimedRun,
    Clock,
    CostRecorderFactory,
    DraftIdFactoryFactory,
    Failure,
    PersistedTei,
    ProviderCallRecordRequest,
    SequentialDraftIds,
    classify_failure,
    draft_generated_payload,
    draft_request,
    project_presenter_profiles,
    provider_call_record,
    require_episode,
    source_from_document,
)
from episodic.logging import get_logger, log_error, log_info
from episodic.observability import (
    MonotonicClockPort,
    NoopTracer,
    NoopValueMetrics,
    PerfCounterClock,
    TracerPort,
    ValueMetricsPort,
)

if typ.TYPE_CHECKING:
    import collections.abc as cabc
    import uuid

    from episodic.canonical.object_store import ObjectStorePort
    from episodic.canonical.unit_of_work_protocols import CanonicalUnitOfWork
    from episodic.generation.draft_script import (
        DraftScriptGenerator,
        DraftScriptResult,
    )

type TaskSet = set[asyncio.Task[None]]

_DEFAULT_MAX_CONCURRENCY = 4
_DEFAULT_MAX_PENDING_RUNS = 16
_DEFAULT_LEASE_SECONDS = 900
_METRIC_TERMINAL_STATES = "generation_run_terminal_total"
_METRIC_DRAFT_ERRORS = "generation_run_draft_errors_total"
_METRIC_QA_BYPASS = "generation_run_qa_bypass_total"
_METRIC_DRAFT_LATENCY = "generation_run_draft_latency_ms"
_METRIC_ADMISSION_REJECTED = "generation_run_admission_rejected_total"
_METRIC_PENDING_DEPTH = "generation_run_pending_depth"

logger = get_logger(__name__)


class GenerationRunLauncher(typ.Protocol):
    """Port for scheduling asynchronous generation-run execution."""

    async def launch(self, run_id: uuid.UUID) -> None:
        """Schedule generation for one run."""


class GenerationRunAdmissionError(RuntimeError):
    """Raised when a launcher cannot retain another pending run."""


@dc.dataclass(frozen=True, slots=True)
class _ExecutionOutcome:
    """Describe the terminal result of one launcher task."""

    outcome: str
    failure_category: str | None = None


@dc.dataclass(slots=True)
class InProcessGenerationRunLauncher(GenerationRunLauncher):
    """Schedule and execute no-QA draft generation in-process."""

    uow_factory: cabc.Callable[[], CanonicalUnitOfWork]
    draft_generator: DraftScriptGenerator
    object_store: ObjectStorePort | None = None
    cost_recorder_factory: CostRecorderFactory | None = None
    clock: Clock = lambda: dt.datetime.now(dt.UTC)
    draft_id_factory_factory: DraftIdFactoryFactory = SequentialDraftIds
    provider_name: str = "openai"
    provider_operation: str = "chat_completions"
    max_concurrency: int = _DEFAULT_MAX_CONCURRENCY
    max_pending_runs: int = _DEFAULT_MAX_PENDING_RUNS
    lease_seconds: int = _DEFAULT_LEASE_SECONDS
    metrics: ValueMetricsPort = dc.field(default_factory=NoopValueMetrics)
    tracer: TracerPort = dc.field(default_factory=NoopTracer)
    monotonic_clock: MonotonicClockPort = dc.field(default_factory=PerfCounterClock)
    _tasks: TaskSet = dc.field(default_factory=set, init=False)
    _task_run_ids: dict[asyncio.Task[None], uuid.UUID] = dc.field(
        default_factory=dict,
        init=False,
    )
    _semaphore: asyncio.Semaphore = dc.field(init=False)
    _admitted_run_count: int = dc.field(default=0, init=False)
    _cancelled_run_ids: set[uuid.UUID] = dc.field(default_factory=set, init=False)
    _is_shutting_down: bool = dc.field(default=False, init=False)

    def __post_init__(self) -> None:
        """Validate and initialise launcher state."""
        if self.max_concurrency < 1:
            msg = "max_concurrency must be at least 1."
            raise ValueError(msg)
        if self.max_pending_runs < 0:
            msg = "max_pending_runs must be non-negative."
            raise ValueError(msg)
        self._semaphore = asyncio.Semaphore(self.max_concurrency)

    async def launch(self, run_id: uuid.UUID) -> None:
        """Schedule a background task for one generation run."""
        self._admit()
        try:
            task = asyncio.create_task(
                self._run_task(run_id),
                name=f"generation-run-{run_id}",
            )
        except Exception:
            self._admitted_run_count -= 1
            self._record_pending_depth()
            raise
        self._tasks.add(task)
        self._task_run_ids[task] = run_id
        task.add_done_callback(self._discard_task)
        log_info(logger, "generation_run_launcher.scheduled run_id=%s", run_id)

    async def drain(self) -> None:
        """Wait for all currently scheduled tasks to finish."""
        while self._tasks:
            await asyncio.gather(*tuple(self._tasks), return_exceptions=True)

    @property
    def scheduled_run_count(self) -> int:
        """Return the number of background runs retained by the launcher."""
        return len(self._tasks)

    async def shutdown(self) -> None:
        """Cancel and drain all scheduled generation tasks."""
        self._is_shutting_down = True
        cancelled_tasks = tuple(
            (task, self._task_run_ids[task]) for task in self._tasks if not task.done()
        )
        for task, _ in cancelled_tasks:
            task.cancel()
        await self.drain()
        for task, run_id in cancelled_tasks:
            if task.cancelled() and run_id not in self._cancelled_run_ids:
                await self._record_cancellation(run_id)
                self._cancelled_run_ids.add(run_id)

    def _discard_task(self, task: asyncio.Task[None]) -> None:
        """Remove finished tasks from the strong-reference registry."""
        self._tasks.discard(task)
        self._task_run_ids.pop(task, None)
        self._admitted_run_count -= 1
        self._record_pending_depth()

    def _admit(self) -> None:
        """Reserve bounded capacity before creating a background task."""
        if self._is_shutting_down:
            self.metrics.increment_counter(
                _METRIC_ADMISSION_REJECTED,
                labels={"reason": "shutdown"},
            )
            msg = "Generation run admission is closed during shutdown."
            raise GenerationRunAdmissionError(msg)
        capacity = self.max_concurrency + self.max_pending_runs
        if self._admitted_run_count >= capacity:
            self.metrics.increment_counter(
                _METRIC_ADMISSION_REJECTED,
                labels={"reason": "capacity"},
            )
            msg = "Generation run admission capacity is exhausted."
            raise GenerationRunAdmissionError(msg)
        self._admitted_run_count += 1
        self._record_pending_depth()

    async def _run_task(self, run_id: uuid.UUID) -> None:
        """Execute one scheduled generation run."""
        with self.tracer.start_span(
            "generation_run.execute",
            attributes={"operation": "generation_run.execute", "run_id": str(run_id)},
        ) as span:
            try:
                async with self._semaphore:
                    outcome = await self._execute_run(run_id)
            except asyncio.CancelledError:
                span.set_attribute("outcome", "cancelled")
                span.set_attribute("failure_category", "launcher.shutdown")
                await asyncio.shield(self._record_cancellation(run_id))
                self._cancelled_run_ids.add(run_id)
                raise
            else:
                span.set_attribute("outcome", outcome.outcome)
                if outcome.failure_category is not None:
                    span.set_attribute("failure_category", outcome.failure_category)

    async def _execute_run(self, run_id: uuid.UUID) -> _ExecutionOutcome:
        """Execute one generation run while its concurrency permit is held."""
        try:
            claimed = await self._claim(run_id)
            if claimed is None:
                return _ExecutionOutcome(outcome="not_claimed")
            result = await self._generate(claimed)
            await self._record_draft_generated(claimed.run.id, result)
            await self._persist_success(claimed, result)
            return _ExecutionOutcome(outcome="completed")
        except Exception as exc:  # noqa: BLE001  # Task boundary must persist unexpected failures.
            failure = classify_failure(exc)
            await self._record_failure(run_id, failure)
            return _ExecutionOutcome(
                outcome="failed",
                failure_category=failure.category,
            )

    async def _record_cancellation(self, run_id: uuid.UUID) -> None:
        """Record cancellation consistently before or during execution."""
        await self._record_failure(
            run_id,
            Failure(
                message="Generation task cancelled during shutdown.",
                category="launcher.shutdown",
            ),
        )

    async def _claim(self, run_id: uuid.UUID) -> ClaimedRun | None:
        """Claim a pending run and load generation input data."""
        async with self.uow_factory() as uow:
            started_at = self.clock()
            run = await uow.generation_runs.claim_run_for_execution(
                run_id,
                current_node="draft",
                started_at=started_at,
                lease_expires_at=started_at + dt.timedelta(seconds=self.lease_seconds),
            )
            if run is None:
                await uow.rollback()
                return None
            episode = await require_episode(uow, run.episode_id)
            documents = await uow.source_documents.list_for_job(run.source_bundle_id)
            source_inputs = [
                await source_from_document(document, self.object_store)
                for document in documents
            ]
            sources = tuple(source_inputs)
            presenter_profiles = project_presenter_profiles(
                await resolve_bindings(
                    uow,
                    series_profile_id=episode.series_profile_id,
                    episode_id=episode.id,
                )
            )
            await uow.generation_runs.append_event(
                run.id,
                kind="run.started",
                payload={"current_node": "draft"},
                occurred_at=started_at,
            )
            await uow.commit()
        self.metrics.increment_counter(
            _METRIC_QA_BYPASS,
            labels={"quality_mode": run.quality_mode.value},
        )
        return ClaimedRun(
            run=run,
            episode=episode,
            sources=sources,
            presenter_profiles=presenter_profiles,
        )

    async def _generate(self, claimed: ClaimedRun) -> DraftScriptResult:
        """Generate one draft and record latency metrics."""
        start = self.monotonic_clock.monotonic_seconds()
        try:
            return await self.draft_generator.generate(
                draft_request(
                    claimed=claimed,
                    clock=self.clock,
                    id_factory_factory=self.draft_id_factory_factory,
                )
            )
        finally:
            elapsed_ms = (self.monotonic_clock.monotonic_seconds() - start) * 1000
            self.metrics.observe_latency_ms(
                _METRIC_DRAFT_LATENCY,
                elapsed_ms,
                labels={"quality_mode": claimed.run.quality_mode.value},
            )

    async def _record_draft_generated(
        self,
        run_id: uuid.UUID,
        result: DraftScriptResult,
    ) -> None:
        """Record that draft generation returned a provider response."""
        async with self.uow_factory() as uow:
            await uow.generation_runs.append_event(
                run_id,
                kind="draft.generated",
                payload=draft_generated_payload(result),
                occurred_at=self.clock(),
            )
            await uow.commit()

    async def _persist_success(
        self,
        claimed: ClaimedRun,
        result: DraftScriptResult,
    ) -> None:
        """Persist generated TEI, cost records, and terminal success."""
        async with self.uow_factory() as uow:
            updated_episode = await persist_draft_script(
                uow,
                DraftScriptPersistenceRequest(
                    episode_id=claimed.run.episode_id,
                    generation_run_id=claimed.run.id,
                    result=result,
                    expected_revision=claimed.episode.tei_revision,
                    clock=self.clock,
                ),
            )
            await self._record_success_events_and_costs(
                uow,
                claimed,
                result,
                PersistedTei(
                    revision=updated_episode.tei_revision,
                    content_hash=updated_episode.tei_content_hash,
                ),
            )
            await uow.commit()
        self._record_terminal_metric(GenerationRunStatus.SUCCEEDED, "none")
        log_info(
            logger,
            "generation_run_launcher.succeeded run_id=%s",
            claimed.run.id,
        )

    async def _record_success_events_and_costs(
        self,
        uow: CanonicalUnitOfWork,
        claimed: ClaimedRun,
        result: DraftScriptResult,
        persisted_tei: PersistedTei,
    ) -> None:
        """Record success-side events, costs, and terminal status."""
        await uow.generation_runs.append_event(
            claimed.run.id,
            kind="tei.persisted",
            payload={
                "tei_revision": persisted_tei.revision,
                "content_hash": persisted_tei.content_hash,
                "qa_status": QaStatus.SKIPPED.value,
            },
            occurred_at=self.clock(),
        )
        await self._record_costs(uow, claimed.run.id, result)
        await uow.generation_runs.append_event(
            claimed.run.id,
            kind="run.succeeded",
            payload={"current_node": "complete"},
            occurred_at=self.clock(),
        )
        await uow.generation_runs.update_run_status(
            claimed.run.id,
            update=GenerationRunStatusUpdate(
                status=GenerationRunStatus.SUCCEEDED,
                current_node="complete",
                ended_at=self.clock(),
            ),
        )

    async def _record_costs(
        self,
        uow: CanonicalUnitOfWork,
        run_id: uuid.UUID,
        result: DraftScriptResult,
    ) -> None:
        """Record provider-call and roll-up cost entries when configured."""
        if self.cost_recorder_factory is None:
            return
        recorder = self.cost_recorder_factory(uow)
        if recorder is None:
            return
        billing_period_key = BillingPeriodKey(self.clock().strftime("%Y-%m"))
        await recorder.pin_run_pricing(
            str(run_id),
            (
                CostProviderOperation(
                    provider_name=self.provider_name,
                    model=result.model,
                    operation=self.provider_operation,
                ),
            ),
            billing_period_key,
        )
        await recorder.record_provider_call(
            provider_call_record(
                ProviderCallRecordRequest(
                    run_id=run_id,
                    provider_name=self.provider_name,
                    provider_operation=self.provider_operation,
                    billing_period_key=billing_period_key,
                    result=result,
                    recorded_at=self.clock(),
                )
            )
        )
        await recorder.finalize_run(str(run_id), "draft")

    async def _record_failure(self, run_id: uuid.UUID, failure: Failure) -> None:
        """Record a terminal failed run state."""
        async with self.uow_factory() as uow:
            try:
                await self._append_failure_events(uow, run_id, failure)
                await uow.generation_runs.update_run_status(
                    run_id,
                    update=GenerationRunStatusUpdate(
                        status=GenerationRunStatus.FAILED,
                        current_node="failed",
                        ended_at=self.clock(),
                        error_message=failure.message,
                        error_category=failure.category,
                    ),
                )
                await uow.commit()
            except RunAlreadyTerminal, RunNotFound:
                await uow.rollback()
                return
        self._record_terminal_metric(GenerationRunStatus.FAILED, failure.category)
        self.metrics.increment_counter(
            _METRIC_DRAFT_ERRORS,
            labels={"error_category": failure.category},
        )
        log_error(
            logger,
            "generation_run_launcher.failed run_id=%s category=%s",
            run_id,
            failure.category,
        )

    async def _append_failure_events(
        self,
        uow: CanonicalUnitOfWork,
        run_id: uuid.UUID,
        failure: Failure,
    ) -> None:
        """Append failure-related events before terminal status mutation."""
        if failure.should_emit_invalid_tei:
            await uow.generation_runs.append_event(
                run_id,
                kind="tei.invalid",
                payload={"error_category": failure.category},
                occurred_at=self.clock(),
            )
        await uow.generation_runs.append_event(
            run_id,
            kind="run.failed",
            payload={
                "error_message": failure.message,
                "error_category": failure.category,
            },
            occurred_at=self.clock(),
        )

    def _record_terminal_metric(
        self,
        status: GenerationRunStatus,
        error_category: str,
    ) -> None:
        """Record the terminal-state counter."""
        self.metrics.increment_counter(
            _METRIC_TERMINAL_STATES,
            labels={"status": status.value, "error_category": error_category},
        )

    def _record_pending_depth(self) -> None:
        """Report bounded work waiting beyond the execution capacity."""
        pending_depth = max(0, self._admitted_run_count - self.max_concurrency)
        self.metrics.observe_value(
            _METRIC_PENDING_DEPTH,
            float(pending_depth),
            labels={},
        )


__all__ = [
    "GenerationRunLauncher",
    "InProcessGenerationRunLauncher",
]
