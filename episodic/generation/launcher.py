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

import dataclasses as dc
import datetime as dt
import typing as typ

from episodic.generation.launcher_claim import (
    DEFAULT_LEASE_SECONDS,
    GenerationRunClaimer,
)
from episodic.generation.launcher_persistence import GenerationRunPersistence
from episodic.generation.launcher_scheduling import (
    DEFAULT_MAX_CONCURRENCY,
    DEFAULT_MAX_PENDING_RUNS,
    ExecutionOutcome,
    GenerationRunScheduler,
)
from episodic.generation.launcher_scheduling import (
    GenerationRunAdmissionError as GenerationRunAdmissionError,
)
from episodic.generation.launcher_support import (
    BoundedSourceLoader,
    Clock,
    CostRecorderFactory,
    DraftIdFactoryFactory,
    Failure,
    GenerationSourceLimits,
    GenerationSourceLoader,
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
    from episodic.canonical.object_store import ObjectStorePort
    from episodic.canonical.unit_of_work_protocols import CanonicalUnitOfWork
    from episodic.generation.draft_script import (
        DraftScriptGenerator,
        DraftScriptSource,
    )
    from episodic.generation.launcher_support import SourceDocumentLoader

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


@dc.dataclass(frozen=True, slots=True)
class _LauncherSchedulerRuntime:
    """Live view of a launcher's scheduling observability and admission limits.

    The scheduler owns the task registry and therefore outlives any single
    run, so it cannot snapshot these launcher fields the way the per-run
    components do.
    """

    launcher: InProcessGenerationRunLauncher

    @property
    def metrics(self) -> ValueMetricsPort:
        """The launcher's current metrics sink."""
        return self.launcher.metrics

    @property
    def tracer(self) -> TracerPort:
        """The launcher's current tracer."""
        return self.launcher.tracer

    @property
    def max_concurrency(self) -> int:
        """The launcher's current execution capacity."""
        return self.launcher.max_concurrency

    @property
    def max_pending_runs(self) -> int:
        """The launcher's current pending-run capacity."""
        return self.launcher.max_pending_runs


@dc.dataclass(frozen=True, slots=True)
class _LauncherSourceLoadRuntime:
    """Live view of the launcher's source-loading collaborators."""

    launcher: InProcessGenerationRunLauncher

    @property
    def object_store(self) -> ObjectStorePort | None:
        """The launcher's current object store."""
        return self.launcher.object_store

    @property
    def source_limits(self) -> GenerationSourceLimits:
        """The launcher's current source limits."""
        return self.launcher.source_limits

    @property
    def load_document(self) -> SourceDocumentLoader:
        """The module's patchable source-document loader."""
        return _load_source_document


@dc.dataclass(frozen=True, slots=True)
class _LauncherClaimerRuntime:
    """Live view of the launcher's claim-stage collaborators."""

    launcher: InProcessGenerationRunLauncher

    @property
    def uow_factory(self) -> cabc.Callable[[], CanonicalUnitOfWork]:
        """The launcher's current unit-of-work factory."""
        return self.launcher.uow_factory

    @property
    def draft_generator(self) -> DraftScriptGenerator:
        """The launcher's current draft generator."""
        return self.launcher.draft_generator

    @property
    def source_loader(self) -> GenerationSourceLoader:
        """A loader over the launcher's current source-loading collaborators."""
        return BoundedSourceLoader(runtime=_LauncherSourceLoadRuntime(self.launcher))

    @property
    def clock(self) -> Clock:
        """The launcher's current clock."""
        return self.launcher.clock

    @property
    def source_limits(self) -> GenerationSourceLimits:
        """The launcher's current source limits."""
        return self.launcher.source_limits

    @property
    def metrics(self) -> ValueMetricsPort:
        """The launcher's current metrics sink."""
        return self.launcher.metrics

    @property
    def monotonic_clock(self) -> MonotonicClockPort:
        """The launcher's current monotonic clock."""
        return self.launcher.monotonic_clock

    @property
    def draft_id_factory_factory(self) -> DraftIdFactoryFactory:
        """The launcher's current draft-id factory factory."""
        return self.launcher.draft_id_factory_factory

    @property
    def lease_seconds(self) -> int:
        """The launcher's current lease duration."""
        return self.launcher.lease_seconds


@dc.dataclass(frozen=True, slots=True)
class _LauncherPersistenceRuntime:
    """Live view of the launcher's persistence-stage collaborators."""

    launcher: InProcessGenerationRunLauncher

    @property
    def uow_factory(self) -> cabc.Callable[[], CanonicalUnitOfWork]:
        """The launcher's current unit-of-work factory."""
        return self.launcher.uow_factory

    @property
    def clock(self) -> Clock:
        """The launcher's current clock."""
        return self.launcher.clock

    @property
    def cost_recorder_factory(self) -> CostRecorderFactory | None:
        """The launcher's current cost-recorder factory."""
        return self.launcher.cost_recorder_factory

    @property
    def provider_name(self) -> str:
        """The launcher's current provider name."""
        return self.launcher.provider_name

    @property
    def provider_operation(self) -> str:
        """The launcher's current provider operation."""
        return self.launcher.provider_operation

    @property
    def metrics(self) -> ValueMetricsPort:
        """The launcher's current metrics sink."""
        return self.launcher.metrics


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

    async def _execute_run(self, run_id: uuid.UUID) -> ExecutionOutcome:
        """Execute one generation run while its concurrency permit is held."""
        claimer = GenerationRunClaimer(runtime=_LauncherClaimerRuntime(self))
        persistence = GenerationRunPersistence(
            runtime=_LauncherPersistenceRuntime(self)
        )
        try:
            claimed = await claimer.claim(run_id)
            if claimed is None:
                return ExecutionOutcome(outcome="not_claimed")
            result = await claimer.generate(claimed)
            await persistence.record_draft_generated(claimed.run.id, result)
            await persistence.persist_success(claimed, result)
            return ExecutionOutcome(outcome="completed")
        except Exception as exc:  # ruff: ignore[blind-except]  # Task boundary must persist unexpected failures.
            failure = classify_failure(exc)
            await persistence.record_failure(run_id, failure)
            return ExecutionOutcome(
                outcome="failed",
                failure_category=failure.category,
            )

    async def _record_cancellation(self, run_id: uuid.UUID) -> None:
        """Record cancellation consistently before or during execution."""
        await GenerationRunPersistence(
            runtime=_LauncherPersistenceRuntime(self)
        ).record_failure(
            run_id,
            Failure(
                message="Generation task cancelled during shutdown.",
                category="launcher.shutdown",
            ),
        )
