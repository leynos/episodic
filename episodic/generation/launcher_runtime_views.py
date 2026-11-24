"""Live runtime views over a generation-run launcher's collaborators.

Each view reads the launcher's current fields when the scheduler or a
persistence step needs them, so a launcher whose sinks are replaced after
construction still observes the replacement.
"""

import dataclasses as dc
import typing as typ

from episodic.generation.launcher_support import BoundedSourceLoader

if typ.TYPE_CHECKING:
    import collections.abc as cabc

    from episodic.canonical.object_store import ObjectStorePort
    from episodic.canonical.unit_of_work_protocols import CanonicalUnitOfWork
    from episodic.generation.draft_script import DraftScriptGenerator
    from episodic.generation.launcher import InProcessGenerationRunLauncher
    from episodic.generation.launcher_support import (
        Clock,
        CostRecorderFactory,
        DraftIdFactoryFactory,
        GenerationSourceLimits,
        GenerationSourceLoader,
        SourceDocumentLoader,
    )
    from episodic.observability import (
        MonotonicClockPort,
        TracerPort,
        ValueMetricsPort,
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

    @property
    def cancellation_write_timeout_seconds(self) -> float:
        """The launcher's current cancellation-write deadline."""
        return self.launcher.cancellation_write_timeout_seconds


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
        from episodic.generation import launcher as launcher_module

        return launcher_module._load_source_document


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
    def reconcile_timeout_seconds(self) -> float:
        """The launcher's current cancelled-claim reconciliation deadline."""
        return self.launcher.cancellation_write_timeout_seconds

    @property
    def lease_seconds(self) -> int:
        """The launcher's current lease duration."""
        return self.launcher.lease_seconds
