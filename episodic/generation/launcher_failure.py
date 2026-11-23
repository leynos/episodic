"""Record a generation run's terminal failure.

:class:`_FailurePersistenceMixin` supplies the authority check, the failure
write and the observation that follow a failed run. Authority is a
:class:`~episodic.generation.launcher_support.ClaimToken`: a caller either
holds one or must win the pending-to-running compare-and-set before the write
proceeds. The token is retained only after the failure transaction commits, so
a rollback cannot leave authority that no durable write backs.
"""

import typing as typ

from episodic.canonical.domain import GenerationRunStatus
from episodic.canonical.generation_run_errors import RunAlreadyTerminal, RunNotFound
from episodic.canonical.generation_run_ports import GenerationRunStatusUpdate
from episodic.generation.launcher_quality import qa_result_payload
from episodic.generation.launcher_support import (
    ClaimToken,
    Failure,
    FailureWrite,
    FailureWriteResult,
    RunClaim,
)
from episodic.logging import get_logger, log_error, log_info

if typ.TYPE_CHECKING:
    import uuid

    from episodic.canonical.unit_of_work_protocols import CanonicalUnitOfWork
    from episodic.generation.draft_script import DraftScriptResult

_METRIC_DRAFT_ERRORS = "generation_run_draft_errors_total"

logger = get_logger(__name__)

if typ.TYPE_CHECKING:
    from episodic.generation.launcher_host import LauncherHost as _MixinBase
else:
    _MixinBase = object


class _FailurePersistenceMixin(_MixinBase):
    """Write a run's terminal failure and its observation."""

    __slots__ = ()

    async def _record_failure(
        self,
        run_id: uuid.UUID,
        failure: Failure,
        *,
        claim: RunClaim | None = None,
        draft: DraftScriptResult | None = None,
    ) -> FailureWriteResult:
        """Record a terminal failed run state when this invocation owns it.

        Parameters
        ----------
        run_id : uuid.UUID
            Run to fail.
        failure : Failure
            Stable failure details, including an optional QA escalation.
        claim : RunClaim | None
            This invocation's claim record. ``None`` asserts that the caller
            already holds authority and must supply ``draft``-free escalation
            only through :meth:`_record_owned_failure`.
        draft : DraftScriptResult | None
            Draft that consumed inference, when the failure is QA escalation.
            Its provider cost is still recorded.

        Returns
        -------
        FailureWriteResult
            Whether the failure was written, and the token that authorized it.
        """
        token = await self._failure_authority(run_id, claim)
        if token is None:
            return FailureWriteResult(written=False)
        return await self._commit_and_observe(
            FailureWrite(run_id=run_id, failure=failure, token=token, draft=draft),
        )

    async def _failure_authority(
        self,
        run_id: uuid.UUID,
        claim: RunClaim | None,
    ) -> ClaimToken | None:
        """Return the token authorizing this failure write, if any.

        Returns
        -------
        ClaimToken | None
            The claim's existing token, a freshly won one, or ``None`` when
            another launcher owns the run.

        Raises
        ------
        ValueError
            If no claim is supplied. Authority must be explicit: a caller
            that already holds a token uses :meth:`_record_owned_failure`.
        """
        if claim is None:
            msg = "a failure write requires a claim or an owned token"
            raise ValueError(msg)
        if claim.token is not None:
            return claim.token
        async with self.uow_factory() as uow:
            try:
                token = await self._claim_for_failure(uow, run_id)
            except RunAlreadyTerminal, RunNotFound:
                # The run is gone or already terminal: not this invocation's
                # to fail, and not an error in the failure path.
                await uow.rollback()
                return None
            if token is None:
                await uow.rollback()
                log_info(
                    logger,
                    "generation_run_launcher.failure_not_owned run_id=%s",
                    run_id,
                )
            return token

    async def _record_owned_failure(
        self,
        run_id: uuid.UUID,
        failure: Failure,
        token: ClaimToken,
        *,
        draft: DraftScriptResult | None = None,
    ) -> FailureWriteResult:
        """Record a failure for a caller that already holds a token.

        Returns
        -------
        FailureWriteResult
            Whether the failure was written, and the token used.
        """
        return await self._commit_and_observe(
            FailureWrite(run_id=run_id, failure=failure, token=token, draft=draft),
        )

    async def _commit_and_observe(self, write: FailureWrite) -> FailureWriteResult:
        """Commit one failure write, then record its observation.

        Returns
        -------
        FailureWriteResult
            Whether the write landed, and the token that authorized it.
        """
        written = await self._write_failure(write)
        if written:
            self._record_failure_observation(write.run_id, write.failure)
        return FailureWriteResult(written=written, token=write.token)

    async def _write_failure(self, write: FailureWrite) -> bool:
        """Write the failure events, costs and terminal status in one commit.

        Returns
        -------
        bool
            ``True`` when the transaction committed.
        """
        async with self.uow_factory() as uow:
            try:
                await self._append_failure_events(uow, write.run_id, write.failure)
                if write.draft is not None:
                    await self._record_costs(uow, write.run_id, write.draft)
                await uow.generation_runs.update_run_status(
                    write.run_id,
                    update=GenerationRunStatusUpdate(
                        status=GenerationRunStatus.FAILED,
                        current_node=None,
                        ended_at=self.clock(),
                        error_message=write.failure.message,
                        error_category=write.failure.category,
                        qa_status=write.failure.qa_status,
                    ),
                )
                await uow.commit()
            except RunAlreadyTerminal, RunNotFound:
                await uow.rollback()
                return False
        return True

    def _record_failure_observation(
        self,
        run_id: uuid.UUID,
        failure: Failure,
    ) -> None:
        """Record the metrics and log line for a written failure."""
        self._record_terminal_metric(GenerationRunStatus.FAILED, failure.category)
        if failure.is_draft_error:
            self.metrics.increment_counter(
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
                occurred_at=self.clock(),
            )
            await uow.generation_runs.append_event(
                run_id,
                kind="qa.escalated",
                payload={
                    "reason": failure.escalation.verdict.value,
                    "content_hash": failure.escalation.content_hash,
                },
                occurred_at=self.clock(),
            )
        if failure.should_emit_invalid_tei:
            await uow.generation_runs.append_event(
                run_id,
                kind="tei.invalid",
                payload={"error_category": failure.category},
                occurred_at=self.clock(),
            )
        await uow.generation_runs.append_event(
            run_id,
            kind="run.failed",
            payload={
                "error_message": failure.message,
                "error_category": failure.category,
            },
            occurred_at=self.clock(),
        )
