"""Live runtime views over a generation-run launcher's collaborators.

Each view is a small, purpose-shaped object graph built once from the
launcher's current fields. A view reads its own attributes rather than
reaching back into the launcher, so a stage sees only the collaborators it
actually uses.

The one deliberate exception is source loading: ``_LauncherSourceLoadRuntime``
prefers an explicitly injected loader but otherwise resolves the module's
patchable seam at call time, because existing tests replace that seam.
"""

import dataclasses as dc
import typing as typ

from episodic.generation.launcher_support import BoundedSourceLoader

if typ.TYPE_CHECKING:
    import collections.abc as cabc

    from episodic.canonical.object_store import ObjectStorePort
    from episodic.canonical.unit_of_work_protocols import CanonicalUnitOfWork
    from episodic.generation.draft_script import DraftScriptGenerator
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


@typ.runtime_checkable
class _SchedulerHost(typ.Protocol):
    """Launcher fields the scheduler view reads.

    Each view is typed against a narrow per-stage host rather than the whole
    launcher, so the dependency is explicit in the type and a view cannot
    reach collaborators its stage never uses. Reads still go through the host
    at use time, which keeps the live-replacement contract.
    """

    @property
    def metrics(self) -> ValueMetricsPort:
        """Sink for admission and pending-depth metrics."""

    @property
    def tracer(self) -> TracerPort:
        """Sink for the per-run execution span."""

    @property
    def max_concurrency(self) -> int:
        """Maximum runs allowed to execute concurrently."""

    @property
    def max_pending_runs(self) -> int:
        """Maximum runs allowed to wait beyond the execution capacity."""

    @property
    def cancellation_write_timeout_seconds(self) -> float:
        """Maximum time shutdown waits for one cancellation write."""


@typ.runtime_checkable
class _ClaimerHost(typ.Protocol):
    """Launcher fields the claim view reads."""

    @property
    def uow_factory(self) -> cabc.Callable[[], CanonicalUnitOfWork]:
        """Factory for detached units of work."""

    @property
    def draft_generator(self) -> DraftScriptGenerator:
        """Generator invoked with the hydrated draft request."""

    @property
    def clock(self) -> Clock:
        """Clock for claim timestamps and events."""

    @property
    def source_limits(self) -> GenerationSourceLimits:
        """Bounds applied to the source bundle."""

    @property
    def metrics(self) -> ValueMetricsPort:
        """Sink for QA-bypass and latency metrics."""

    @property
    def monotonic_clock(self) -> MonotonicClockPort:
        """Clock used to measure draft latency."""

    @property
    def draft_id_factory_factory(self) -> DraftIdFactoryFactory:
        """Factory for the per-request TEI identifier generator."""

    @property
    def lease_seconds(self) -> int:
        """Claim lease duration recorded with the started run."""

    @property
    def reconcile_timeout_seconds(self) -> float:
        """Maximum time a cancelled claim waits for reconciliation."""

    @property
    def object_store(self) -> ObjectStorePort | None:
        """Store used to read uploaded source content."""

    @property
    def source_document_loader(self) -> SourceDocumentLoader:
        """Injected source-document loader."""


@typ.runtime_checkable
class _PersistenceHost(typ.Protocol):
    """Launcher fields the persistence view reads."""

    @property
    def uow_factory(self) -> cabc.Callable[[], CanonicalUnitOfWork]:
        """Factory for detached units of work."""

    @property
    def clock(self) -> Clock:
        """Clock for event timestamps and terminals."""

    @property
    def cost_recorder_factory(self) -> CostRecorderFactory | None:
        """Factory that binds a cost recorder to a unit of work."""

    @property
    def provider_name(self) -> str:
        """Provider name recorded with costs."""

    @property
    def provider_operation(self) -> str:
        """Provider operation recorded with costs."""

    @property
    def metrics(self) -> ValueMetricsPort:
        """Sink for terminal-state metrics."""


@typ.runtime_checkable
class _SourceLoadHost(typ.Protocol):
    """Launcher fields the source-load view reads."""

    @property
    def object_store(self) -> ObjectStorePort | None:
        """Store used to read uploaded source content."""

    @property
    def source_limits(self) -> GenerationSourceLimits:
        """Bounds applied to each source document."""

    @property
    def source_document_loader(self) -> SourceDocumentLoader:
        """Injected source-document loader."""


@dc.dataclass(frozen=True, slots=True)
class _LauncherSchedulerRuntime:
    """Scheduling observability and admission limits for one scheduler."""

    launcher: _SchedulerHost

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

    launcher: _PersistenceHost

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

    launcher: _SourceLoadHost

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
        """The launcher's injected source-document loader."""
        return self.launcher.source_document_loader


@dc.dataclass(frozen=True, slots=True)
class _LauncherClaimerRuntime:
    """Live view of the launcher's claim-stage collaborators."""

    launcher: _ClaimerHost

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
        """The launcher's own cancelled-claim reconciliation deadline."""
        return self.launcher.reconcile_timeout_seconds

    @property
    def lease_seconds(self) -> int:
        """The launcher's current lease duration."""
        return self.launcher.lease_seconds
