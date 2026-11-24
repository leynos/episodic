"""Record a generation run's terminal failure with explicit launcher authority.

:class:`GenerationRunFailurePersistence` owns failure writes. Authority is a
:class:`~episodic.generation.launcher_support.ClaimToken`: a caller either
holds one or the component claims, or reconciles, the run inside the same
transaction as the write. The token is retained only after the commit, so a
rollback cannot leave authority no durable write backs.

Scope of that authority: it is enforced here, by the launcher, not by the
repository. ``update_run_status`` accepts no token; its locks and terminal
checks are what protect concurrent writers, and the pending-to-running claim
is the store-level guard. A holder of a token therefore names the *launcher
invocation* that may write, which routes and audits ownership; it is not a
store-enforced fence against a caller that bypasses this component.
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
type RecordCostsAuthority = cabc.Callable[
    [CanonicalUnitOfWork, uuid.UUID, DraftScriptResult],
    cabc.Awaitable[None],
]


@dc.dataclass(slots=True)
class GenerationRunFailurePersistence:
    """Write a run's terminal failure and its observation."""

    runtime: PersistenceRuntime
    claim_for_failure: ClaimAuthority | None = None
    record_costs: RecordCostsAuthority | None = None

    async def record_failure(
        self,
        run_id: uuid.UUID,
        failure: Failure,
        *,
        claim: RunClaim,
        draft: DraftScriptResult | None = None,
    ) -> FailureWriteResult:
        """Record a terminal failed run state.

        Authority is checked by this launcher component against the caller's
        claim token, not by ``update_run_status``, which takes no token.

        Parameters
        ----------
        run_id : uuid.UUID
            Identifier of the run to mark failed.
        failure : Failure
            Stable failure details, including an optional QA escalation.
        claim : RunClaim
            This invocation's claim record. When it holds no token, the write
            proceeds only if the authority callables can reconcile or claim
            the run.
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
        claim.token = token
        self._record_failure_observation(run_id, failure)
        return FailureWriteResult(written=True, token=token)

    async def _failure_authority(
        self,
        uow: CanonicalUnitOfWork,
        run_id: uuid.UUID,
        claim: RunClaim,
    ) -> ClaimToken | None:
        """Return the token authorizing this failure write, if any.

        Returns
        -------
        ClaimToken | None
            The existing token, a reconciled or freshly claimed one, or
            ``None`` when another launcher owns the run or the cached token
            names a different run.
        """
        if claim.token is not None:
            if claim.token.run_id != run_id:
                # A token names one run. Accepting another run's token would
                # let a caller fail a run this invocation never claimed, and
                # the store's row lock does not check ownership.
                log_info(
                    logger,
                    "generation_run_launcher.foreign_claim_token run_id=%s",
                    run_id,
                )
                return None
            return claim.token
        # Reconcile through the caller's unit of work, not a second one: a
        # nested unit of work would run hidden I/O inside this command's open
        # transaction. The proof comparison is the same rule the claimer uses.
        stored = await uow.generation_runs.claim_token_for(run_id)
        if stored == claim.proof:
            return ClaimToken(run_id)
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
