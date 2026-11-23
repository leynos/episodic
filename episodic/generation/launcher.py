"""Schedule and execute bounded no-QA generation runs in the API process.

The public :class:`GenerationRunLauncher` port and
:class:`InProcessGenerationRunLauncher` service connect the generation-run API
resource to canonical run persistence. The launcher claims a
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

The launcher is the orchestration boundary. Task admission and lifecycle live
in :class:`~episodic.generation.launcher_scheduling.GenerationRunScheduler`,
claim-and-hydrate logic lives in
:class:`~episodic.generation.launcher_claim.GenerationRunClaimer`, and outcome
persistence lives in
:class:`~episodic.generation.launcher_persistence.GenerationRunPersistence`.
Each component takes its collaborators as constructor arguments; the launcher
composes them once in ``__post_init__`` and translates a classified failure
into the persisted terminal record.
"""

import asyncio
import dataclasses as dc
import datetime as dt
import typing as typ

from episodic.canonical.generation_graph_ports import (
    ContentGenerationGraphPort,
    ContentGenerationRequest,
)
from episodic.canonical.generation_routing import (
    GenerationTerminal,
    route_quality_mode,
    terminal_outcome,
)
from episodic.generation.launcher_claim import (
    DEFAULT_LEASE_SECONDS,
    GenerationRunClaimer,
)
from episodic.generation.launcher_failure import GenerationRunFailurePersistence
from episodic.generation.launcher_persistence import GenerationRunPersistence
from episodic.generation.launcher_runtime_views import (
    _LauncherClaimerRuntime,
    _LauncherPersistenceRuntime,
    _LauncherSchedulerRuntime,
)
from episodic.generation.launcher_scheduling import (
    DEFAULT_MAX_CONCURRENCY,
    DEFAULT_MAX_PENDING_RUNS,
    ExecutionOutcome,
    GenerationRunScheduler,
)
from episodic.generation.launcher_scheduling import (
    GenerationRunAdmissionError as GenerationRunAdmissionError,
)
from episodic.generation.launcher_session import (
    RunNotClaimedError,
    _LauncherRunSession,
)
from episodic.generation.launcher_support import (
    Clock,
    CostRecorderFactory,
    DraftIdFactoryFactory,
    Failure,
    GenerationSourceLimits,
    RunClaim,
    SequentialDraftIds,
    classify_failure,
    source_from_document,
)
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

    from episodic.canonical.domain import SourceDocument
    from episodic.canonical.generation_quality import QualityMode
    from episodic.canonical.object_store import ObjectStorePort
    from episodic.canonical.unit_of_work_protocols import CanonicalUnitOfWork
    from episodic.generation.draft_script import (
        DraftScriptGenerator,
        DraftScriptSource,
    )

__all__ = [
    "GenerationRunLauncher",
    "InProcessGenerationRunLauncher",
]


class GenerationRunLauncher(typ.Protocol):
    """Port for scheduling asynchronous generation-run execution."""

    async def launch(self, run_id: uuid.UUID) -> None:
        """Schedule generation for one run."""


async def _load_source_document(
    document: SourceDocument,
    object_store: ObjectStorePort | None,
    limits: GenerationSourceLimits | None = None,
    *,
    remaining_aggregate_bytes: int | None = None,
) -> DraftScriptSource:
    """Load one source document through this module's patchable binding.

    Resolving ``source_from_document`` here, rather than capturing it when the
    launcher is constructed, preserves the pre-split patch point at hydration
    time.

    Returns
    -------
    DraftScriptSource
        Bounded generator source input for the canonical document.
    """
    return await source_from_document(
        document,
        object_store,
        limits,
        remaining_aggregate_bytes=remaining_aggregate_bytes,
    )


@dc.dataclass(slots=True)
class InProcessGenerationRunLauncher(GenerationRunLauncher):
    """Schedule and execute no-QA draft generation in-process.

    Attributes
    ----------
    uow_factory : cabc.Callable[[], CanonicalUnitOfWork]
        Factory for the detached units of work used by claim and persistence.
    draft_generator : DraftScriptGenerator
        Generator invoked with each claimed run's hydrated draft request.
    object_store : ObjectStorePort | None
        Store used to read uploaded source content.
    cost_recorder_factory : CostRecorderFactory | None
        Factory that binds a cost recorder to a persistence unit of work.
    clock : Clock
        Clock for lifecycle timestamps and draft requests.
    draft_id_factory_factory : DraftIdFactoryFactory
        Factory for the per-request TEI identifier generator.
    provider_name : str
        Provider name recorded in pinned pricing and provider-call costs.
    provider_operation : str
        Provider operation recorded in cost records.
    max_concurrency : int
        Maximum runs allowed to execute concurrently.
    max_pending_runs : int
        Maximum runs allowed to wait beyond the execution capacity.
    lease_seconds : int
        Claim lease duration recorded with each started run.
    source_limits : GenerationSourceLimits
        Count and byte bounds applied to each run's source bundle.
    metrics : ValueMetricsPort
        Sink for admission, pending-depth, terminal, and latency metrics.
    tracer : TracerPort
        Sink for the per-run execution span.
    monotonic_clock : MonotonicClockPort
        Clock used to measure draft-generation latency.
    """

    uow_factory: cabc.Callable[[], CanonicalUnitOfWork]
    draft_generator: DraftScriptGenerator
    content_graph: ContentGenerationGraphPort
    object_store: ObjectStorePort | None = None
    cost_recorder_factory: CostRecorderFactory | None = None
    clock: Clock = lambda: dt.datetime.now(dt.UTC)
    draft_id_factory_factory: DraftIdFactoryFactory = SequentialDraftIds
    provider_name: str = "openai"
    provider_operation: str = "chat_completions"
    max_concurrency: int = DEFAULT_MAX_CONCURRENCY
    max_pending_runs: int = DEFAULT_MAX_PENDING_RUNS
    lease_seconds: int = DEFAULT_LEASE_SECONDS
    source_limits: GenerationSourceLimits = dc.field(
        default_factory=GenerationSourceLimits
    )
    metrics: ValueMetricsPort = dc.field(default_factory=NoopValueMetrics)
    tracer: TracerPort = dc.field(default_factory=NoopTracer)
    monotonic_clock: MonotonicClockPort = dc.field(default_factory=PerfCounterClock)
    _scheduler: GenerationRunScheduler = dc.field(init=False)

    def __post_init__(self) -> None:
        """Compose the long-lived scheduler over the launcher's ports."""
        self._scheduler = GenerationRunScheduler(
            execute_run=self._execute_run,
            record_cancellation=self._record_cancellation,
            runtime=_LauncherSchedulerRuntime(self),
        )

    async def launch(self, run_id: uuid.UUID) -> None:
        """Schedule a background task for one generation run."""
        await self._scheduler.launch(run_id)

    async def drain(self) -> None:
        """Wait for all currently scheduled tasks to finish."""
        await self._scheduler.drain()

    @property
    def scheduled_run_count(self) -> int:
        """The number of background runs retained by the launcher."""
        return self._scheduler.scheduled_run_count

    async def shutdown(self) -> None:
        """Cancel and drain all scheduled generation tasks."""
        await self._scheduler.shutdown()

    async def _execute_run(
        self,
        run_id: uuid.UUID,
        claim: RunClaim,
    ) -> ExecutionOutcome:
        """Execute one generation run through the content-generation graph."""
        claimer, persistence, failures = self._components()
        session = _LauncherRunSession(
            claimer=claimer,
            persistence=persistence,
            failures=failures,
            uow_factory=self.uow_factory,
            clock=self.clock,
            metrics=self.metrics,
            run_id=run_id,
            claim=claim,
        )
        try:
            quality_mode = await self._read_quality_mode(run_id)
            if quality_mode is None:
                return ExecutionOutcome(outcome="not_claimed")
            terminal = await self.content_graph.run(
                ContentGenerationRequest(run_id=run_id, quality_mode=quality_mode),
                steps=session,
            )
        except RunNotClaimedError:
            return ExecutionOutcome(outcome="not_claimed")
        except asyncio.CancelledError:
            await self._scheduler.record_cancellation_owned(run_id, claim)
            raise
        except Exception as exc:  # ruff: ignore[blind-except]  # Task boundary must persist unexpected failures.
            failure = classify_failure(exc)
            result = await failures.record_failure(run_id, failure, claim=claim)
            if not result.written:
                return ExecutionOutcome(outcome="not_claimed")
            return ExecutionOutcome(
                outcome="failed",
                failure_category=failure.category,
            )
        branch = route_quality_mode(quality_mode)
        return ExecutionOutcome(
            outcome=_terminal_outcome_name(terminal),
            quality_branch=branch.value,
            terminal=terminal.value,
        )

    def _components(
        self,
    ) -> tuple[
        GenerationRunClaimer,
        GenerationRunPersistence,
        GenerationRunFailurePersistence,
    ]:
        """Compose the per-run claim, success and failure components."""
        claimer = GenerationRunClaimer(runtime=_LauncherClaimerRuntime(self))
        persistence = GenerationRunPersistence(
            runtime=_LauncherPersistenceRuntime(self)
        )
        failures = GenerationRunFailurePersistence(
            runtime=_LauncherPersistenceRuntime(self),
            claim_for_failure=claimer.claim_for_failure,
            reconcile_claim=claimer.reconcile,
            record_costs=persistence.record_costs,
        )
        return claimer, persistence, failures

    async def _read_quality_mode(self, run_id: uuid.UUID) -> QualityMode | None:
        """Read a run's requested quality mode before the graph forks on it."""
        async with self.uow_factory() as uow:
            run = await uow.generation_runs.get_run(run_id)
        return None if run is None else run.quality_mode

    async def _record_cancellation(
        self,
        run_id: uuid.UUID,
        claim: RunClaim,
    ) -> bool:
        """Record cancellation consistently before or during execution."""
        _claimer, _persistence, failures = self._components()
        result = await failures.record_failure(
            run_id,
            Failure(
                message="Generation task cancelled during shutdown.",
                category="launcher.shutdown",
            ),
            claim=claim,
        )
        return result.written


def _terminal_outcome_name(terminal: GenerationTerminal) -> str:
    """Name the span outcome a terminal records."""
    outcome = terminal_outcome(terminal)
    return "escalated" if outcome.error_category is not None else "completed"
