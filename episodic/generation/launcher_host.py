"""Typing contract for the in-process launcher's mixins.

:class:`~episodic.generation.launcher.InProcessGenerationRunLauncher` is
composed from scheduling, claim, and persistence mixins. Each mixin reads the
launcher's dataclass fields and calls methods another mixin defines, so the
type checker needs one declaration of that shared surface. The mixins inherit
from :class:`LauncherHost` only while type checking; at runtime their base is
``object``, so this protocol adds nothing to the launcher's MRO.
"""

import typing as typ

if typ.TYPE_CHECKING:
    import asyncio
    import collections.abc as cabc
    import uuid

    from episodic.canonical.domain import SourceDocument
    from episodic.canonical.object_store import ObjectStorePort
    from episodic.canonical.unit_of_work_protocols import CanonicalUnitOfWork
    from episodic.generation.draft_script import (
        DraftScriptGenerator,
        DraftScriptResult,
        DraftScriptSource,
    )
    from episodic.generation.launcher_support import (
        ClaimedRun,
        Clock,
        CostRecorderFactory,
        DraftIdFactoryFactory,
        Failure,
        GenerationSourceLimits,
    )
    from episodic.observability import (
        MonotonicClockPort,
        TracerPort,
        ValueMetricsPort,
    )


class LauncherHost(typ.Protocol):
    """Fields and cross-mixin methods the launcher mixins rely on."""

    uow_factory: cabc.Callable[[], CanonicalUnitOfWork]
    draft_generator: DraftScriptGenerator
    object_store: ObjectStorePort | None
    cost_recorder_factory: CostRecorderFactory | None
    clock: Clock
    draft_id_factory_factory: DraftIdFactoryFactory
    provider_name: str
    provider_operation: str
    max_concurrency: int
    max_pending_runs: int
    lease_seconds: int
    source_limits: GenerationSourceLimits
    metrics: ValueMetricsPort
    tracer: TracerPort
    monotonic_clock: MonotonicClockPort
    _tasks: set[asyncio.Task[None]]
    _task_run_ids: dict[asyncio.Task[None], uuid.UUID]
    _semaphore: asyncio.Semaphore
    _admitted_run_count: int
    _cancelled_run_ids: set[uuid.UUID]
    _is_shutting_down: bool

    async def _load_sources(
        self,
        documents: list[SourceDocument],
    ) -> tuple[DraftScriptSource, ...]:
        """Load bounded source text for a claimed run."""
        ...

    async def _claim(self, run_id: uuid.UUID) -> ClaimedRun | None:
        """Claim a pending run and hydrate its input."""
        ...

    async def _generate(self, claimed: ClaimedRun) -> DraftScriptResult:
        """Generate one draft for a claimed run."""
        ...

    async def _record_draft_generated(
        self,
        run_id: uuid.UUID,
        result: DraftScriptResult,
    ) -> None:
        """Record the draft-generated lifecycle event."""
        ...

    async def _persist_success(
        self,
        claimed: ClaimedRun,
        result: DraftScriptResult,
    ) -> None:
        """Persist a successful run's TEI, costs, and terminal status."""
        ...

    async def _record_failure(self, run_id: uuid.UUID, failure: Failure) -> None:
        """Record a terminal failed run state."""
        ...

    def _record_pending_depth(self) -> None:
        """Report bounded work waiting beyond the execution capacity."""
        ...
