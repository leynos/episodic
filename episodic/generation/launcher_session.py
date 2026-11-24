"""Per-run session through which content-generation nodes reach run state.

The launcher creates one session per run and hands it to the graph as the
step port. Every method runs inline in the run's own launcher task, which
keeps the launcher the single writer of that run's events and status: nodes
never open a unit of work and never touch a repository directly.

The session holds the claimed run and the generated draft. Nothing here is
persisted between steps, matching the plan's decision to keep application
objects out of graph state until roadmap item 4.4.4 introduces a durable draft
artefact.
"""

import dataclasses as dc
import typing as typ

from episodic.canonical.domain import GenerationRunStatus
from episodic.canonical.generation_graph_ports import (
    EvaluationSubject,
    QualityEvaluation,
)
from episodic.canonical.generation_persistence import InvalidDraftTeiError
from episodic.canonical.generation_quality import QaStatus
from episodic.canonical.generation_routing import QualityVerdict
from episodic.canonical.generation_run_ports import GenerationRunStatusUpdate
from episodic.canonical.tei import parse_tei_header
from episodic.generation.launcher_quality import QaOutcome, record_qa_metrics
from episodic.generation.launcher_support import (
    ClaimedRun,
    ClaimToken,
    Failure,
    FailureWriteResult,
    RunClaim,
)

if typ.TYPE_CHECKING:
    import collections.abc as cabc
    import uuid

    from episodic.canonical.unit_of_work_protocols import CanonicalUnitOfWork
    from episodic.generation.draft_script import DraftScriptResult
    from episodic.observability import ValueMetricsPort
    from episodic.runtime_providers import Clock


class ClaimerSteps(typ.Protocol):
    """The claim and generation operations one run session may call."""

    async def claim(
        self,
        run_id: uuid.UUID,
        claim: RunClaim | None = None,
    ) -> ClaimedRun | None:
        """Claim and hydrate the run."""
        ...

    async def generate(self, claimed: ClaimedRun) -> DraftScriptResult:
        """Generate one draft."""
        ...


class FailureSteps(typ.Protocol):
    """The failure-recording operation one run session may call."""

    async def record_failure(
        self,
        run_id: uuid.UUID,
        failure: Failure,
        *,
        claim: RunClaim,
        draft: DraftScriptResult | None = None,
    ) -> FailureWriteResult:
        """Record a terminal failure."""
        ...


class SessionPersistenceSteps(typ.Protocol):
    """The persistence operations one run session may call."""

    async def record_draft_generated(
        self,
        run_id: uuid.UUID,
        result: DraftScriptResult,
    ) -> None:
        """Record that generation returned a draft."""
        ...

    async def persist_success(
        self,
        claimed: ClaimedRun,
        result: DraftScriptResult,
        *,
        qa: QaOutcome | None = None,
    ) -> None:
        """Persist a successful run."""
        ...


class RunNotClaimedError(Exception):
    """Raised when a scheduled run was claimed elsewhere or no longer exists."""


@dc.dataclass(slots=True)
class _LauncherRunSession:
    """Step port implementation for one claimed run.

    Attributes
    ----------
    claimer : ClaimerSteps
        Claim and generation component for this run.
    persistence : SessionPersistenceSteps
        Success-side persistence component.
    failures : FailureSteps
        Failure persistence component.
    uow_factory : cabc.Callable[[], CanonicalUnitOfWork]
        Factory for the session's own short units of work.
    clock : Clock
        Clock for lifecycle timestamps.
    metrics : ValueMetricsPort
        Metrics sink for QA gate observations.
    run_id : uuid.UUID
        The run this session serves.
    claim : RunClaim
        Per-invocation claim record shared with the scheduling task.
    claimed : ClaimedRun | None
        Hydrated run input, set by :meth:`initialize`.
    draft : DraftScriptResult | None
        Generated draft, set by :meth:`generate_draft`.
    """

    claimer: ClaimerSteps
    persistence: SessionPersistenceSteps
    failures: FailureSteps
    uow_factory: cabc.Callable[[], CanonicalUnitOfWork]
    clock: Clock
    metrics: ValueMetricsPort
    run_id: uuid.UUID
    claim: RunClaim
    claimed: ClaimedRun | None = None
    draft: DraftScriptResult | None = None

    async def initialize(self) -> None:
        """Claim and hydrate the run.

        Raises
        ------
        RunNotClaimedError
            If the run is absent or was claimed by another worker, so the
            graph must stop before spending inference.
        """
        claimed = await self.claimer.claim(self.run_id, self.claim)
        if claimed is None:
            msg = f"generation run {self.run_id} was not claimed"
            raise RunNotClaimedError(msg)
        self.claimed = claimed

    async def generate_draft(self) -> None:
        """Generate one draft, record it, and validate it as TEI.

        Raises
        ------
        InvalidDraftTeiError
            If the generated draft is not parseable TEI. QA must never judge
            invalid TEI, and persistence would reject it anyway.
        """
        claimed = self._require_claimed()
        result = await self.claimer.generate(claimed)
        await self.persistence.record_draft_generated(claimed.run.id, result)
        try:
            parse_tei_header(result.tei_xml)
        except (TypeError, ValueError) as exc:
            raise InvalidDraftTeiError(str(exc)) from exc
        self.draft = result

    async def begin_evaluation(self, evaluator_names: tuple[str, ...]) -> None:
        """Record that evaluation started and expose the current node."""
        draft = self._require_draft()
        async with self.uow_factory() as uow:
            await uow.generation_runs.append_event(
                self.run_id,
                kind="qa.evaluation_started",
                payload={
                    "current_node": "evaluate",
                    "evaluators": list(evaluator_names),
                    "content_hash": draft.content_hash,
                },
                occurred_at=self.clock(),
            )
            await uow.generation_runs.update_run_status(
                self.run_id,
                update=GenerationRunStatusUpdate(
                    status=GenerationRunStatus.RUNNING,
                    current_node="evaluate",
                    ended_at=None,
                ),
            )
            await uow.commit()

    def evaluation_subject(self) -> EvaluationSubject:
        """Return the generated draft as an evaluation subject."""
        claimed = self._require_claimed()
        draft = self._require_draft()
        return EvaluationSubject(
            run_id=claimed.run.id,
            episode_id=claimed.run.episode_id,
            tei_xml=draft.tei_xml,
            content_hash=draft.content_hash,
        )

    async def complete_with_draft(
        self,
        qa_status: QaStatus,
        evaluations: tuple[QualityEvaluation, ...],
    ) -> None:
        """Persist the draft and record the successful terminal."""
        claimed = self._require_claimed()
        draft = self._require_draft()
        await self.persistence.persist_success(
            claimed,
            draft,
            qa=QaOutcome(qa_status, evaluations),
        )
        # Record the QA outcome only after the terminal write commits, so a
        # failed persistence cannot emit a passing verdict.
        if qa_status is QaStatus.PASSED:
            record_qa_metrics(
                self.metrics,
                QualityVerdict.PASSED,
                evaluations,
            )

    async def escalate(
        self,
        verdict: QualityVerdict,
        evaluations: tuple[QualityEvaluation, ...],
    ) -> None:
        """Record the escalated terminal without persisting TEI."""
        draft = self._require_draft()
        token = self._require_token()
        self.claim.token = token
        result = await self.failures.record_failure(
            self.run_id,
            Failure.escalation_failure(
                verdict=verdict,
                evaluations=evaluations,
                content_hash=draft.content_hash,
            ),
            claim=self.claim,
            draft=draft,
        )
        if not result.written:
            msg = f"generation run {self.run_id} refused the escalation write"
            raise RunNotClaimedError(msg)
        # The escalation is durable now, so its QA outcome metrics are real.
        record_qa_metrics(self.metrics, verdict, evaluations)

    def _require_token(self) -> ClaimToken:
        """Return this session's claim token, or fail loudly without one."""
        if self.claim.token is None:
            msg = "run session has no claim token"
            raise RuntimeError(msg)
        return self.claim.token

    def _require_claimed(self) -> ClaimedRun:
        """Return the hydrated run or fail loudly if a node skipped hydration."""
        if self.claimed is None:
            msg = "run session used before initialize"
            raise RuntimeError(msg)
        return self.claimed

    def _require_draft(self) -> DraftScriptResult:
        """Return the generated draft or fail loudly if generation was skipped."""
        if self.draft is None:
            msg = "run session used before generate_draft"
            raise RuntimeError(msg)
        return self.draft
