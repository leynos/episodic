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

import datetime as dt
import typing as typ

from episodic.canonical.generation_quality import QualityMode
from episodic.canonical.reference_documents import resolve_bindings
from episodic.generation.launcher_support import (
    ClaimedRun,
    GenerationSourceLimitError,
    draft_request,
    project_presenter_profiles,
    require_episode,
)

if typ.TYPE_CHECKING:
    import uuid

    from episodic.canonical.domain import GenerationRun
    from episodic.generation.draft_script import DraftScriptResult

_METRIC_QA_BYPASS = "generation_run_qa_bypass_total"
_METRIC_DRAFT_LATENCY = "generation_run_draft_latency_ms"


if typ.TYPE_CHECKING:
    from episodic.generation.launcher_host import LauncherHost as _MixinBase
else:
    _MixinBase = object


class _ClaimMixin(_MixinBase):
    """Claim a pending run and hydrate it for draft generation."""

    __slots__ = ()

    async def _hydrate(self, run_id: uuid.UUID) -> ClaimedRun | None:
        """Claim a pending run, then load its input outside the claim transaction.

        Parameters
        ----------
        run_id : uuid.UUID
            Run to claim.

        Returns
        -------
        ClaimedRun | None
            Hydrated run input, or ``None`` if another worker claimed the run
            or it is already terminal.

        """  # ruff: ignore[docstring-missing-exception]  # The limit error is raised by a helper.
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
        sources = await self._load_sources(documents)
        if run.quality_mode is QualityMode.DRAFT_WITHOUT_QA:
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
