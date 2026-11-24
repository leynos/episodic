"""Claim generation runs and hydrate them into a draft-generation request.

:class:`GenerationRunClaimer` owns the claim-and-hydrate path: it durably
marks a run started, loads its episode and resolved presenter bindings through
a fresh unit of work, loads bounded source text through an injected
:class:`~episodic.generation.launcher_support_sources.GenerationSourceLoader`,
and generates the draft script. Its collaborators arrive through a narrow
:class:`ClaimerRuntime` view, so the component can be constructed with fakes
and each collaborator is read at its use site rather than snapshotted.
"""

import asyncio
import contextlib
import dataclasses as dc
import datetime as dt
import typing as typ

from episodic.canonical.generation_claim import ExecutionClaim
from episodic.canonical.generation_quality import QualityMode
from episodic.canonical.reference_documents import resolve_bindings
from episodic.generation.launcher_support import (
    ClaimedRun,
    ClaimedRunResult,
    ClaimToken,
    Clock,
    GenerationSourceLimitError,
    GenerationSourceLimits,
    RunClaim,
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
#: How long a cancelled claim commit waits for its shielded reconciliation.
#: Shutdown must not hang on a stalled read, and an unverified claim is not
#: adopted: the durable row either carries this attempt's proof or it does not.
DEFAULT_RECONCILE_TIMEOUT_SECONDS = 10.0
_METRIC_QA_BYPASS = "generation_run_qa_bypass_total"
_METRIC_DRAFT_LATENCY = "generation_run_draft_latency_ms"


class ClaimerRuntime(typ.Protocol):
    """Live claim-stage collaborators consulted at their use sites.

    Properties rather than values keep the component's reads aligned with the
    pre-split launcher, which read each field when it reached that stage.
    """

    @property
    def uow_factory(self) -> cabc.Callable[[], CanonicalUnitOfWork]:
        """Factory for the detached units of work used by claim and hydration."""

    @property
    def draft_generator(self) -> DraftScriptGenerator:
        """Generator invoked with the hydrated draft request."""

    @property
    def source_loader(self) -> GenerationSourceLoader:
        """Loader that bounds and hydrates canonical source documents."""

    @property
    def clock(self) -> Clock:
        """Clock for claim timestamps, events, and draft requests."""

    @property
    def source_limits(self) -> GenerationSourceLimits:
        """Count and byte bounds applied to the source bundle."""

    @property
    def metrics(self) -> ValueMetricsPort:
        """Sink for QA-bypass and draft-latency metrics."""

    @property
    def monotonic_clock(self) -> MonotonicClockPort:
        """Clock used to measure draft-generation latency."""

    @property
    def draft_id_factory_factory(self) -> DraftIdFactoryFactory:
        """Factory for the per-request TEI identifier generator."""

    @property
    def lease_seconds(self) -> int:
        """Claim lease duration recorded with the started run."""

    @property
    def reconcile_timeout_seconds(self) -> float:
        """Maximum time a cancelled claim waits for reconciliation."""


@dc.dataclass(frozen=True, slots=True)
class ClaimerContext:
    """Value-backed claimer runtime for direct construction and tests.

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
    reconcile_timeout_seconds: float = DEFAULT_RECONCILE_TIMEOUT_SECONDS


@dc.dataclass(slots=True)
class GenerationRunClaimer:
    """Claim pending runs and generate one draft for each claimed run.

    Attributes
    ----------
    runtime : ClaimerRuntime
        Live view of the claim-stage collaborators.
    """

    runtime: ClaimerRuntime

    async def claim(
        self,
        run_id: uuid.UUID,
        claim: RunClaim | None = None,
    ) -> ClaimedRun | None:
        """Claim a pending run, then load its input outside the claim transaction.

        The claim and its ``run.started`` event are committed before hydration
        begins, so a later failure does not undo the claim. Hydration then runs
        in a second, short unit of work, and bound source text is loaded after
        that unit of work closes.

        Parameters
        ----------
        run_id : uuid.UUID
            Identifier of the pending generation run to claim.
        claim : RunClaim | None
            Per-invocation claim record. Its token is set as soon as the claim
            commits, which also carries authority out of a cancelled claim;
            ``_claim_and_start`` reports the same token in its result.

        Returns
        -------
        ClaimedRun | None
            The claimed run with its episode, bounded sources, and presenter
            profiles, or ``None`` when another worker won the claim.

        Raises
        ------
        GenerationSourceLimitError.source_count
            If the run's source bundle exceeds the configured source count.
        """
        claim = claim or RunClaim()
        result = await self._claim_and_start(run_id, claim)
        if result is None:
            return None
        run = result.run
        claim.token = result.token
        async with self.runtime.uow_factory() as uow:
            episode = await require_episode(uow, run.episode_id)
            documents = await uow.source_documents.list_for_job(run.source_bundle_id)
            if len(documents) > self.runtime.source_limits.max_source_count:
                raise GenerationSourceLimitError.source_count()
            presenter_profiles = project_presenter_profiles(
                await resolve_bindings(
                    uow,
                    series_profile_id=episode.series_profile_id,
                    episode_id=episode.id,
                )
            )
        sources = await self.runtime.source_loader.load(documents)
        if run.quality_mode is QualityMode.DRAFT_WITHOUT_QA:
            self.runtime.metrics.increment_counter(
                _METRIC_QA_BYPASS,
                labels={"quality_mode": run.quality_mode.value},
            )
        return ClaimedRun(
            run=run,
            episode=episode,
            sources=sources,
            presenter_profiles=presenter_profiles,
            token=result.token,
        )

    async def generate(self, claimed: ClaimedRun) -> DraftScriptResult:
        """Generate one draft and record latency metrics.

        Draft latency is observed from the injected monotonic clock on both
        success and failure, because the observation runs in a ``finally``
        block. Generator exceptions propagate unchanged for the caller to
        classify.

        Parameters
        ----------
        claimed : ClaimedRun
            Claimed run, episode, sources, and presenter profiles to generate
            from.

        Returns
        -------
        DraftScriptResult
            Generated TEI, content hash, usage, and provider metadata.
        """
        start = self.runtime.monotonic_clock.monotonic_seconds()
        try:
            return await self.runtime.draft_generator.generate(
                draft_request(
                    claimed=claimed,
                    clock=self.runtime.clock,
                    id_factory_factory=self.runtime.draft_id_factory_factory,
                )
            )
        finally:
            elapsed_ms = (
                self.runtime.monotonic_clock.monotonic_seconds() - start
            ) * 1000
            self.runtime.metrics.observe_latency_ms(
                _METRIC_DRAFT_LATENCY,
                elapsed_ms,
                labels={"quality_mode": claimed.run.quality_mode.value},
            )

    async def _claim_and_start(
        self,
        run_id: uuid.UUID,
        claim: RunClaim,
    ) -> ClaimedRunResult | None:
        """Linearize a claim and make its started event durable before hydration.

        Returns
        -------
        ClaimedRunResult | None
            The claimed run and the token that authorizes later writes, or
            ``None`` when another invocation owns it.

        Raises
        ------
        asyncio.CancelledError
            If cancelled; the claim is reconciled against the durable row
            first so a committed claim keeps an owner. This is the one path
            that must adopt the token in place, because the record has to
            carry authority out of a call that never returns; the claim's
            token is therefore also set here.
        """
        async with self.runtime.uow_factory() as uow:
            started_at = self.runtime.clock()
            run = await uow.generation_runs.claim_run_for_execution(
                run_id,
                ExecutionClaim(
                    current_node="draft",
                    started_at=started_at,
                    lease_expires_at=started_at
                    + dt.timedelta(seconds=self.runtime.lease_seconds),
                    claim_token=claim.proof,
                ),
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
            try:
                await uow.commit()
            except asyncio.CancelledError:
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(
                        asyncio.shield(self.reconcile(run_id, claim)),
                        timeout=self.runtime.reconcile_timeout_seconds,
                    )
                raise
            token = ClaimToken(run.id, proof=claim.proof)
            # Cancellation cannot return a value, so the claim carries the
            # token out of this call; every returning path also reports it.
            claim.token = token
        return ClaimedRunResult(run=run, token=token)

    # Two paths write the caller's claim. The cancelled-commit path above must
    # do so in place: cancellation cannot return a value, so the claim is the
    # only way to carry authority out of the call. `claim()` also copies the
    # returned token onto the caller-supplied claim, so a later failure write
    # on the same claim already holds authority instead of reconciling.

    async def claim_for_failure(
        self,
        uow: CanonicalUnitOfWork,
        run_id: uuid.UUID,
        claim: RunClaim,
    ) -> ClaimToken | None:
        """Claim a still-pending run so only its owner can fail it.

        The compare-and-set runs inside the caller's transaction, so a won
        claim commits or rolls back with the failure write it authorizes.

        Returns
        -------
        ClaimToken | None
            This invocation's token, or ``None`` when another owns the run.
        """
        started_at = self.runtime.clock()
        run = await uow.generation_runs.claim_run_for_execution(
            run_id,
            ExecutionClaim(
                current_node=None,
                started_at=started_at,
                # No lease: this claim and the terminal write that authorizes
                # it commit in one transaction, so a lease would never become
                # durable without the failure that already ends the run.
                lease_expires_at=None,
                claim_token=claim.proof,
            ),
        )
        return None if run is None else ClaimToken(run_id, proof=claim.proof)

    async def reconcile(
        self,
        run_id: uuid.UUID,
        claim: RunClaim,
    ) -> ClaimToken | None:
        """Re-adopt a durable claim whose commit acknowledgement was lost.

        Returns
        -------
        ClaimToken | None
            The token when the stored claim carries this attempt's proof.
        """
        if claim.token is not None:
            return claim.token
        async with self.runtime.uow_factory() as uow:
            stored = await uow.generation_runs.claim_token_for(run_id)
        if stored != claim.proof:
            return None
        token = ClaimToken(run_id, proof=claim.proof)
        claim.token = token
        return token


__all__ = ["ClaimerContext", "ClaimerRuntime", "GenerationRunClaimer"]
