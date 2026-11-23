"""Record a generation run's terminal failure with explicit authority.

:class:`GenerationRunFailurePersistence` owns failure writes. Authority is a
:class:`~episodic.generation.launcher_support.ClaimToken`: a caller either
holds one or the component claims, or reconciles, the run inside the same
transaction as the write. The token is retained only after the commit, so a
rollback cannot leave authority no durable write backs.
"""

import dataclasses as dc
import typing as typ

from episodic.canonical.domain import GenerationRunStatus
from episodic.canonical.generation_run_errors import RunAlreadyTerminal, RunNotFound
from episodic.canonical.generation_run_ports import GenerationRunStatusUpdate
from episodic.generation.launcher_quality import qa_result_payload
from episodic.generation.launcher_support import (
    ClaimToken,
    Failure,
    FailureWriteResult,
    RunClaim,
)
from episodic.logging import get_logger, log_error, log_info

if typ.TYPE_CHECKING:
    import collections.abc as cabc
    import uuid

    from episodic.canonical.unit_of_work_protocols import CanonicalUnitOfWork
    from episodic.generation.draft_script import DraftScriptResult

    from .launcher_persistence import PersistenceRuntime

_METRIC_TERMINAL_STATES = "generation_run_terminal_total"
_METRIC_DRAFT_ERRORS = "generation_run_draft_errors_total"

logger = get_logger(__name__)

type ClaimAuthority = cabc.Callable[
    [CanonicalUnitOfWork, uuid.UUID, RunClaim],
    cabc.Awaitable[ClaimToken | None],
]
type ReconcileAuthority = cabc.Callable[
    [uuid.UUID, RunClaim],
    cabc.Awaitable[ClaimToken | None],
]
type RecordCostsAuthority = cabc.Callable[
    [CanonicalUnitOfWork, uuid.UUID, DraftScriptResult],
    cabc.Awaitable[None],
]


@dc.dataclass(slots=True)
class GenerationRunFailurePersistence:
    """Write a run's terminal failure and its observation."""

    runtime: PersistenceRuntime
    claim_for_failure: ClaimAuthority | None = None
    reconcile_claim: ReconcileAuthority | None = None
    record_costs: RecordCostsAuthority | None = None

    async def record_failure(
        self,
        run_id: uuid.UUID,
        failure: Failure,
        *,
        claim: RunClaim | None = None,
        draft: DraftScriptResult | None = None,
    ) -> FailureWriteResult:
        """Record a terminal failed run state.

        Parameters
        ----------
        run_id : uuid.UUID
            Identifier of the run to mark failed.
        failure : Failure
            Stable failure details, including an optional QA escalation.
        claim : RunClaim | None
            This invocation's claim record. When supplied without a token, the
            write proceeds only if the authority callables can claim or
            reconcile the run. ``None`` asserts that the caller already holds
            authority.
        draft : DraftScriptResult | None
            Draft that consumed inference, when the failure is an escalation.

        Returns
        -------
        FailureWriteResult
            Whether the failure was written, and the token that authorized it.

        Raises
        ------
        RuntimeError
            If a draft's costs must be recorded but no cost authority is set.
        """
        async with self.runtime.uow_factory() as uow:
            try:
                token = await self._failure_authority(uow, run_id, claim)
                if token is None:
                    return FailureWriteResult(written=False)
                await self._append_failure_events(uow, run_id, failure)
                if draft is not None:
                    if self.record_costs is None:
                        msg = "failure costs require a cost-recording authority"
                        raise RuntimeError(msg)
                    await self.record_costs(uow, run_id, draft)
                await uow.generation_runs.update_run_status(
                    run_id,
                    update=GenerationRunStatusUpdate(
                        status=GenerationRunStatus.FAILED,
                        current_node=None,
                        ended_at=self.runtime.clock(),
                        error_message=failure.message,
                        error_category=failure.category,
                        qa_status=failure.qa_status,
                    ),
                )
                await uow.commit()
            except RunAlreadyTerminal, RunNotFound:
                await uow.rollback()
                return FailureWriteResult(written=False)
        if claim is not None:
            claim.token = token
        self._record_failure_observation(run_id, failure)
        return FailureWriteResult(written=True, token=token)

    async def _failure_authority(
        self,
        uow: CanonicalUnitOfWork,
        run_id: uuid.UUID,
        claim: RunClaim | None,
    ) -> ClaimToken | None:
        """Return the token authorizing this failure write, if any.

        Returns
        -------
        ClaimToken | None
            The existing token, a reconciled or freshly claimed one, or
            ``None`` when another launcher owns the run.
        """
        if claim is None:
            return ClaimToken(run_id)
        if claim.token is not None:
            return claim.token
        if self.reconcile_claim is not None:
            token = await self.reconcile_claim(run_id, claim)
            if token is not None:
                return token
        if self.claim_for_failure is None:
            return None
        try:
            token = await self.claim_for_failure(uow, run_id, claim)
        except RunAlreadyTerminal, RunNotFound:
            return None
        if token is None:
            log_info(
                logger,
                "generation_run_launcher.failure_not_owned run_id=%s",
                run_id,
            )
        return token

    def _record_failure_observation(
        self,
        run_id: uuid.UUID,
        failure: Failure,
    ) -> None:
        """Record the metrics and log line for a written failure."""
        self.runtime.metrics.increment_counter(
            _METRIC_TERMINAL_STATES,
            labels={
                "status": GenerationRunStatus.FAILED.value,
                "error_category": failure.category,
            },
        )
        if failure.is_draft_error:
            self.runtime.metrics.increment_counter(
                _METRIC_DRAFT_ERRORS,
                labels={"error_category": failure.category},
            )
        log_failure = log_error if failure.is_draft_error else log_info
        log_failure(
            logger,
            "generation_run_launcher.failed run_id=%s category=%s",
            run_id,
            failure.category,
        )

    async def _append_failure_events(
        self,
        uow: CanonicalUnitOfWork,
        run_id: uuid.UUID,
        failure: Failure,
    ) -> None:
        """Append failure-related events before terminal status mutation."""
        if failure.escalation is not None:
            await uow.generation_runs.append_event(
                run_id,
                kind="qa.result",
                payload=qa_result_payload(
                    failure.escalation.verdict,
                    failure.escalation.evaluations,
                ),
                occurred_at=self.runtime.clock(),
            )
            await uow.generation_runs.append_event(
                run_id,
                kind="qa.escalated",
                payload={
                    "reason": failure.escalation.verdict.value,
                    "content_hash": failure.escalation.content_hash,
                },
                occurred_at=self.runtime.clock(),
            )
        if failure.should_emit_invalid_tei:
            await uow.generation_runs.append_event(
                run_id,
                kind="tei.invalid",
                payload={"error_category": failure.category},
                occurred_at=self.runtime.clock(),
            )
        await uow.generation_runs.append_event(
            run_id,
            kind="run.failed",
            payload={
                "error_message": failure.message,
                "error_category": failure.category,
            },
            occurred_at=self.runtime.clock(),
        )
