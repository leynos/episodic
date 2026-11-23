"""Hydrate claimed generation runs into a draft-generation request.

:class:`_ClaimMixin` supplies :class:`InProcessGenerationRunLauncher` with the
claim-and-hydrate path: it durably marks a run started, loads its episode and
resolved presenter bindings through a fresh unit of work, and generates the
draft script. Source loading stays with the launcher itself, because tests
monkeypatch ``episodic.generation.launcher.source_from_document`` and the
call must resolve in that module's namespace.

The content-generation graph's ``initialize`` node claims through
:meth:`_ClaimMixin._hydrate`; a run claimed elsewhere or already terminal
hydrates to ``None``, and the session turns that into ``not_claimed``.
"""

import asyncio
import datetime as dt
import typing as typ

from episodic.canonical.domain import GenerationRunStatus
from episodic.canonical.reference_documents import resolve_bindings
from episodic.generation.launcher_support import (
    ClaimedRun,
    ClaimToken,
    GenerationSourceLimitError,
    RunClaim,
    draft_request,
    project_presenter_profiles,
    require_episode,
)

if typ.TYPE_CHECKING:
    import uuid

    from episodic.canonical.domain import GenerationRun
    from episodic.canonical.unit_of_work_protocols import CanonicalUnitOfWork
    from episodic.generation.draft_script import DraftScriptResult

_METRIC_DRAFT_LATENCY = "generation_run_draft_latency_ms"


if typ.TYPE_CHECKING:
    from episodic.generation.launcher_host import LauncherHost as _MixinBase
else:
    _MixinBase = object


class _ClaimMixin(_MixinBase):
    """Claim a pending run and hydrate it for draft generation."""

    __slots__ = ()

    async def _claim_and_hydrate(
        self,
        run_id: uuid.UUID,
        claim: RunClaim,
    ) -> ClaimedRun | None:
        """Claim a pending run, then load its input outside the claim transaction.

        Parameters
        ----------
        run_id : uuid.UUID
            Run to claim.
        claim : RunClaim
            Per-invocation claim record. Its token is set as soon as the claim
            commits, before hydration, so a hydration fault is still written
            by the run's owner.

        Returns
        -------
        ClaimedRun | None
            Hydrated run input, or ``None`` if another worker claimed the run
            or it is already terminal.

        """  # ruff: ignore[docstring-missing-exception]  # The limit error is raised by a helper.
        run = await self._claim_and_start(run_id, claim)
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
        sources = await self._load_sources(documents)
        return ClaimedRun(
            run=run,
            episode=episode,
            sources=sources,
            presenter_profiles=presenter_profiles,
        )

    async def _claim_for_failure(
        self,
        uow: CanonicalUnitOfWork,
        run_id: uuid.UUID,
    ) -> ClaimToken | None:
        """Claim a still-pending run so only its owner can fail it.

        A failure that arrives before this invocation claimed the run, such as
        a failed initial read, may write only when the pending-to-running
        transition succeeds: that compare-and-set is the proof that no other
        launcher owns the run.

        Returns
        -------
        ClaimToken | None
            This invocation's token, or ``None`` when another launcher owns
            the run.
        """
        run = await uow.generation_runs.claim_run_for_execution(
            run_id,
            current_node=None,
            started_at=self.clock(),
            lease_expires_at=None,
        )
        return None if run is None else ClaimToken(run_id)

    async def _claim_and_start(
        self,
        run_id: uuid.UUID,
        claim: RunClaim,
    ) -> GenerationRun | None:
        """Linearize a claim and make its started event durable before hydration.

        The claim's token is stored as soon as the commit returns, inside the
        unit of work, so a failure during session close cannot lose a claim
        that is already durable. Without that ordering the run would stay
        running with no writer entitled to fail it.

        Returns
        -------
        GenerationRun | None
            The claimed run, or ``None`` when another invocation owns it.

        Raises
        ------
        asyncio.CancelledError
            If cancelled; the claim is reconciled against the durable row
            first so a committed claim keeps an owner.
        """
        async with self.uow_factory() as uow:
            started_at = self.clock()
            claim.started_at = started_at
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
            try:
                await uow.commit()
            except asyncio.CancelledError:
                # The commit may have landed. Reconcile against the durable
                # row before the cancellation path gives up on the run.
                await asyncio.shield(self._reconcile_claim(run_id, claim))
                raise
            claim.token = ClaimToken(run.id)
        return run

    async def _reconcile_claim(
        self,
        run_id: uuid.UUID,
        claim: RunClaim,
    ) -> ClaimToken | None:
        """Re-adopt a durable claim whose commit acknowledgement was lost.

        Returns
        -------
        ClaimToken | None
            The token when the stored run carries this attempt's claim.

        Notes
        -----
        Runs under a shield from the cancellation path, so it returns rather
        than raising when the outer task is cancelled again.
        """
        if claim.token is not None or claim.started_at is None:
            return claim.token
        async with self.uow_factory() as uow:
            run = await uow.generation_runs.get_run(run_id)
        reacquired = (
            None if run is None else self._adopt_if_owned(run, run_id, claim.started_at)
        )
        if reacquired is not None:
            claim.token = reacquired
        return reacquired

    @staticmethod
    def _adopt_if_owned(
        run: GenerationRun,
        run_id: uuid.UUID,
        started_at: dt.datetime,
    ) -> ClaimToken | None:
        """Return a token when the stored run is this attempt's claim."""
        owned = run.status is GenerationRunStatus.RUNNING and (
            run.started_at == started_at
        )
        return ClaimToken(run_id) if owned else None

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
