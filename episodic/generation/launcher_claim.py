"""Claim generation runs and hydrate them into a draft-generation request.

:class:`GenerationRunClaimer` owns the claim-and-hydrate path: it durably
marks a run started, loads its episode and resolved presenter bindings through
a fresh unit of work, loads bounded source text through an injected
:class:`~episodic.generation.launcher_support_sources.GenerationSourceLoader`,
and generates the draft script. Its collaborators are explicit fields, so the
component can be constructed with fakes instead of a launcher's shared state.
"""

import dataclasses as dc
import datetime as dt
import typing as typ

from episodic.canonical.reference_documents import resolve_bindings
from episodic.generation.launcher_support import (
    ClaimedRun,
    Clock,
    GenerationSourceLimitError,
    GenerationSourceLimits,
    SequentialDraftIds,
    draft_request,
    project_presenter_profiles,
    require_episode,
)
from episodic.observability import (
    MonotonicClockPort,
    NoopValueMetrics,
    PerfCounterClock,
    ValueMetricsPort,
)

if typ.TYPE_CHECKING:
    import collections.abc as cabc
    import uuid

    from episodic.canonical.domain import GenerationRun
    from episodic.canonical.unit_of_work_protocols import CanonicalUnitOfWork
    from episodic.generation.draft_script import (
        DraftScriptGenerator,
        DraftScriptResult,
    )
    from episodic.generation.launcher_support import (
        DraftIdFactoryFactory,
        GenerationSourceLoader,
    )

DEFAULT_LEASE_SECONDS = 900
_METRIC_QA_BYPASS = "generation_run_qa_bypass_total"
_METRIC_DRAFT_LATENCY = "generation_run_draft_latency_ms"


@dc.dataclass(slots=True)
class GenerationRunClaimer:
    """Claim pending runs and generate one draft for each claimed run.

    Attributes
    ----------
    uow_factory : cabc.Callable[[], CanonicalUnitOfWork]
        Factory for the detached units of work used by claim and hydration.
    draft_generator : DraftScriptGenerator
        Generator invoked with the hydrated draft request.
    source_loader : GenerationSourceLoader
        Loader that bounds and hydrates canonical source documents.
    clock : Clock
        Clock for claim timestamps, events, and draft requests.
    source_limits : GenerationSourceLimits
        Count and byte bounds applied to the source bundle.
    metrics : ValueMetricsPort
        Sink for QA-bypass and draft-latency metrics.
    monotonic_clock : MonotonicClockPort
        Clock used to measure draft-generation latency.
    draft_id_factory_factory : DraftIdFactoryFactory
        Factory for the per-request TEI identifier generator.
    lease_seconds : int
        Claim lease duration recorded with the started run.
    """

    uow_factory: cabc.Callable[[], CanonicalUnitOfWork]
    draft_generator: DraftScriptGenerator
    source_loader: GenerationSourceLoader
    clock: Clock = lambda: dt.datetime.now(dt.UTC)
    source_limits: GenerationSourceLimits = dc.field(
        default_factory=GenerationSourceLimits
    )
    metrics: ValueMetricsPort = dc.field(default_factory=NoopValueMetrics)
    monotonic_clock: MonotonicClockPort = dc.field(default_factory=PerfCounterClock)
    draft_id_factory_factory: DraftIdFactoryFactory = SequentialDraftIds
    lease_seconds: int = DEFAULT_LEASE_SECONDS

    async def claim(self, run_id: uuid.UUID) -> ClaimedRun | None:
        """Claim a pending run, then load its input outside the claim transaction."""
        run = await self._claim_and_start(run_id)
        if run is None:
            return None
        async with self.uow_factory() as uow:
            episode = await require_episode(uow, run.episode_id)
            documents = await uow.source_documents.list_for_job(run.source_bundle_id)
            if len(documents) > self.source_limits.max_source_count:
                raise GenerationSourceLimitError.source_count()
            presenter_profiles = project_presenter_profiles(
                await resolve_bindings(
                    uow,
                    series_profile_id=episode.series_profile_id,
                    episode_id=episode.id,
                )
            )
        sources = await self.source_loader.load(documents, self.source_limits)
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

    async def generate(self, claimed: ClaimedRun) -> DraftScriptResult:
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

    async def _claim_and_start(self, run_id: uuid.UUID) -> GenerationRun | None:
        """Linearize a claim and make its started event durable before hydration."""
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
            await uow.generation_runs.append_event(
                run.id,
                kind="run.started",
                payload={"current_node": "draft"},
                occurred_at=started_at,
            )
            await uow.commit()
        return run


__all__ = ["GenerationRunClaimer"]
