"""Persist generation-run outcomes: draft events, TEI, costs, and status.

:class:`_PersistenceMixin` supplies :class:`InProcessGenerationRunLauncher`
with the write side of a generation run: recording that a draft was
generated, persisting the TEI and its success-side events, recording
provider costs when a cost recorder is configured, and applying the
immutable ``GenerationRunStatusUpdate`` command for both terminal success and
terminal failure. Terminal-state and pending-depth metrics are recorded here
too, alongside the runs they describe.
"""

import dataclasses as dc
import typing as typ

from episodic.canonical.domain import GenerationRunStatus
from episodic.canonical.generation_persistence import (
    DraftScriptPersistenceRequest,
    persist_draft_script,
)
from episodic.canonical.generation_quality import QaStatus
from episodic.canonical.generation_routing import QualityVerdict
from episodic.canonical.generation_run_errors import RunAlreadyTerminal, RunNotFound
from episodic.canonical.generation_run_ports import UNCHANGED, GenerationRunStatusUpdate
from episodic.cost.ports import BillingPeriodKey
from episodic.cost.pricing_snapshot import PricedService
from episodic.cost.recorder import CostProviderOperation
from episodic.generation.launcher_quality import QaOutcome, qa_result_payload
from episodic.generation.launcher_support import (
    Failure,
    PersistedTei,
    ProviderCallRecordRequest,
    RunOwnership,
    draft_generated_payload,
    provider_call_record,
)
from episodic.logging import get_logger, log_error, log_info

if typ.TYPE_CHECKING:
    import uuid

    from episodic.canonical.unit_of_work_protocols import CanonicalUnitOfWork
    from episodic.generation.draft_script import DraftScriptResult
    from episodic.generation.launcher_support import ClaimedRun

_METRIC_TERMINAL_STATES = "generation_run_terminal_total"
_METRIC_DRAFT_ERRORS = "generation_run_draft_errors_total"
_METRIC_PENDING_DEPTH = "generation_run_pending_depth"

logger = get_logger(__name__)


@dc.dataclass(frozen=True, slots=True)
class _SuccessRecord:
    """Persisted artefacts a successful transition records."""

    claimed: ClaimedRun
    result: DraftScriptResult
    persisted_tei: PersistedTei


if typ.TYPE_CHECKING:
    from episodic.generation.launcher_host import LauncherHost as _MixinBase
else:
    _MixinBase = object


class _PersistenceMixin(_MixinBase):
    """Persist draft, success, cost, and failure outcomes for a run."""

    __slots__ = ()

    async def _record_draft_generated(
        self,
        run_id: uuid.UUID,
        result: DraftScriptResult,
    ) -> None:
        """Record that draft generation returned a provider response."""
        async with self.uow_factory() as uow:
            await uow.generation_runs.append_event(
                run_id,
                kind="draft.generated",
                payload=draft_generated_payload(result),
                occurred_at=self.clock(),
            )
            await uow.commit()

    async def _persist_success(
        self,
        claimed: ClaimedRun,
        result: DraftScriptResult,
        *,
        qa: QaOutcome,
    ) -> None:
        """Persist generated TEI, cost records, and terminal success."""
        async with self.uow_factory() as uow:
            updated_episode = await persist_draft_script(
                uow,
                DraftScriptPersistenceRequest(
                    episode_id=claimed.run.episode_id,
                    generation_run_id=claimed.run.id,
                    result=result,
                    expected_revision=claimed.episode.tei_revision,
                    qa_status=qa.status,
                    clock=self.clock,
                ),
            )
            await self._record_success_transition(
                uow,
                _SuccessRecord(
                    claimed=claimed,
                    result=result,
                    persisted_tei=PersistedTei(
                        revision=updated_episode.tei_revision,
                        content_hash=updated_episode.tei_content_hash,
                    ),
                ),
                qa,
            )
            await uow.commit()
        self._record_terminal_metric(GenerationRunStatus.SUCCEEDED, "none")
        log_info(
            logger,
            "generation_run_launcher.succeeded run_id=%s",
            claimed.run.id,
        )

    async def _record_success_transition(
        self,
        uow: CanonicalUnitOfWork,
        record: _SuccessRecord,
        qa: QaOutcome,
    ) -> None:
        """Record success-side events, costs, and terminal status."""
        run_id = record.claimed.run.id
        if qa.status is QaStatus.PASSED:
            await uow.generation_runs.append_event(
                run_id,
                kind="qa.result",
                payload=qa_result_payload(QualityVerdict.PASSED, qa.evaluations),
                occurred_at=self.clock(),
            )
        await uow.generation_runs.append_event(
            run_id,
            kind="tei.persisted",
            payload={
                "tei_revision": record.persisted_tei.revision,
                "content_hash": record.persisted_tei.content_hash,
                "qa_status": qa.status.value,
            },
            occurred_at=self.clock(),
        )
        await self._record_costs(uow, run_id, record.result)
        await uow.generation_runs.append_event(
            run_id,
            kind="run.succeeded",
            payload={"current_node": "complete"},
            occurred_at=self.clock(),
        )
        await uow.generation_runs.update_run_status(
            run_id,
            update=GenerationRunStatusUpdate(
                status=GenerationRunStatus.SUCCEEDED,
                current_node=None,
                ended_at=self.clock(),
                qa_status=(UNCHANGED if qa.status is QaStatus.SKIPPED else qa.status),
            ),
        )

    async def _record_costs(
        self,
        uow: CanonicalUnitOfWork,
        run_id: uuid.UUID,
        result: DraftScriptResult,
    ) -> None:
        """Record provider-call and roll-up cost entries when configured."""
        if self.cost_recorder_factory is None:
            return
        recorder = self.cost_recorder_factory(uow)
        if recorder is None:
            return
        billing_period_key = BillingPeriodKey(self.clock().strftime("%Y-%m"))
        await recorder.pin_run_pricing(
            str(run_id),
            (
                CostProviderOperation(
                    service_kind=PricedService.LLM,
                    provider_name=self.provider_name,
                    model=result.model,
                    operation=self.provider_operation,
                ),
            ),
            billing_period_key,
        )
        await recorder.record_provider_call(
            provider_call_record(
                ProviderCallRecordRequest(
                    run_id=run_id,
                    provider_name=self.provider_name,
                    provider_operation=self.provider_operation,
                    billing_period_key=billing_period_key,
                    result=result,
                    recorded_at=self.clock(),
                )
            )
        )
        await recorder.finalize_run(str(run_id), "draft")

    async def _record_failure(
        self,
        run_id: uuid.UUID,
        failure: Failure,
        *,
        ownership: RunOwnership | None = None,
        draft: DraftScriptResult | None = None,
    ) -> bool:
        """Record a terminal failed run state.

        Parameters
        ----------
        run_id : uuid.UUID
            Run to fail.
        failure : Failure
            Stable failure details, including an optional QA escalation.
        ownership : RunOwnership | None
            Claim record for this invocation. When supplied and still unset,
            the failure is written only if this invocation can claim the
            pending run, so a losing launcher cannot fail another's run.
            ``None`` means the caller has already established ownership.
        draft : DraftScriptResult | None
            Draft that consumed inference, when the failure is QA escalation.
            Its provider cost is still recorded.

        Returns
        -------
        bool
            ``True`` when the failure was written, ``False`` when the run was
            not this invocation's to fail.
        """
        async with self.uow_factory() as uow:
            try:
                if not await self._prepare_failure_write(uow, run_id, ownership):
                    return False
                await self._append_failure_events(uow, run_id, failure)
                if draft is not None:
                    await self._record_costs(uow, run_id, draft)
                await uow.generation_runs.update_run_status(
                    run_id,
                    update=GenerationRunStatusUpdate(
                        status=GenerationRunStatus.FAILED,
                        current_node=None,
                        ended_at=self.clock(),
                        error_message=failure.message,
                        error_category=failure.category,
                        qa_status=failure.qa_status,
                    ),
                )
                await uow.commit()
            except RunAlreadyTerminal, RunNotFound:
                await uow.rollback()
                return False
        if ownership is not None:
            # The claim is durable only once this transaction commits; a
            # rollback must leave the flag unset so a later cancellation
            # retries the compare-and-set instead of trusting a lost claim.
            ownership.claimed = True
        self._record_failure_observation(run_id, failure)
        return True

    async def _prepare_failure_write(
        self,
        uow: CanonicalUnitOfWork,
        run_id: uuid.UUID,
        ownership: RunOwnership | None,
    ) -> bool:
        """Establish ownership before a failure write, or refuse to write.

        Returns
        -------
        bool
            ``True`` when the caller may write the failure, ``False`` when
            another launcher owns the run.
        """
        if ownership is None or ownership.claimed:
            return True
        if await self._claim_for_failure(uow, run_id):
            return True
        await uow.rollback()
        log_info(
            logger,
            "generation_run_launcher.failure_not_owned run_id=%s",
            run_id,
        )
        return False

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

    def _record_terminal_metric(
        self,
        status: GenerationRunStatus,
        error_category: str,
    ) -> None:
        """Record the terminal-state counter."""
        self.metrics.increment_counter(
            _METRIC_TERMINAL_STATES,
            labels={"status": status.value, "error_category": error_category},
        )

    def _record_pending_depth(self) -> None:
        """Report bounded work waiting beyond the execution capacity."""
        pending_depth = max(0, self._admitted_run_count - self.max_concurrency)
        self.metrics.observe_value(
            _METRIC_PENDING_DEPTH,
            float(pending_depth),
            labels={},
        )
