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

Task admission and lifecycle live in :mod:`episodic.generation.launcher_scheduling`,
claim-and-hydrate logic lives in :mod:`episodic.generation.launcher_claim`, and
outcome persistence lives in :mod:`episodic.generation.launcher_persistence`; this
module composes those mixins and keeps ``_load_sources`` local because tests
monkeypatch ``source_from_document`` on this module's namespace.
"""

import asyncio
import dataclasses as dc
import datetime as dt
import typing as typ

from episodic.generation.launcher_claim import _ClaimMixin
from episodic.generation.launcher_persistence import _PersistenceMixin
from episodic.generation.launcher_scheduling import (
    GenerationRunAdmissionError as GenerationRunAdmissionError,
)
from episodic.generation.launcher_scheduling import _SchedulingMixin
from episodic.generation.launcher_support import (
    Clock,
    CostRecorderFactory,
    DraftIdFactoryFactory,
    GenerationSourceLimitError,
    GenerationSourceLimits,
    SequentialDraftIds,
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
    from episodic.generation.draft_script import DraftScriptGenerator, DraftScriptSource

type TaskSet = set[asyncio.Task[None]]

_DEFAULT_MAX_CONCURRENCY = 4
_DEFAULT_MAX_PENDING_RUNS = 16
_DEFAULT_LEASE_SECONDS = 900


class GenerationRunLauncher(typ.Protocol):
    """Port for scheduling asynchronous generation-run execution."""

    async def launch(self, run_id: uuid.UUID) -> None:
        """Schedule generation for one run."""


@dc.dataclass(slots=True)
class InProcessGenerationRunLauncher(
    _SchedulingMixin,
    _ClaimMixin,
    _PersistenceMixin,
    GenerationRunLauncher,
):
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
    source_limits: GenerationSourceLimits = dc.field(
        default_factory=GenerationSourceLimits
    )
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

    async def _load_sources(
        self,
        documents: list[SourceDocument],
    ) -> tuple[DraftScriptSource, ...]:
        """Load bounded source text and reject an aggregate-size overflow."""
        if len(documents) > self.source_limits.max_source_count:
            raise GenerationSourceLimitError.source_count()
        aggregate_bytes = 0
        sources: list[DraftScriptSource] = []
        for document in documents:
            source = await source_from_document(
                document,
                self.object_store,
                self.source_limits,
                remaining_aggregate_bytes=(
                    self.source_limits.max_aggregate_source_bytes - aggregate_bytes
                ),
            )
            aggregate_bytes += len(source.content.encode())
            sources.append(source)
        return tuple(sources)


__all__ = [
    "GenerationRunLauncher",
    "InProcessGenerationRunLauncher",
]
