"""Persist generation-run outcomes: draft events, TEI, costs, and status.

:class:`_PersistenceMixin` supplies :class:`InProcessGenerationRunLauncher`
with the write side of a generation run: recording that a draft was
generated, persisting the TEI and its success-side events, recording
provider costs when a cost recorder is configured, and applying the
immutable ``GenerationRunStatusUpdate`` command for both terminal success and
terminal failure. Terminal-state and pending-depth metrics are recorded here
too, alongside the runs they describe.
"""

import typing as typ

from episodic.canonical.domain import GenerationRunStatus
from episodic.canonical.generation_persistence import (
    DraftScriptPersistenceRequest,
    persist_draft_script,
)
from episodic.canonical.generation_quality import QaStatus
from episodic.canonical.generation_run_errors import RunAlreadyTerminal, RunNotFound
from episodic.canonical.generation_run_ports import GenerationRunStatusUpdate
from episodic.cost.ports import BillingPeriodKey
from episodic.cost.recorder import CostProviderOperation
from episodic.generation.launcher_support import (
    Failure,
    PersistedTei,
    ProviderCallRecordRequest,
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
                    clock=self.clock,
                ),
            )
            await self._record_success_events_and_costs(
                uow,
                claimed,
                result,
                PersistedTei(
                    revision=updated_episode.tei_revision,
                    content_hash=updated_episode.tei_content_hash,
                ),
            )
            await uow.commit()
        self._record_terminal_metric(GenerationRunStatus.SUCCEEDED, "none")
        log_info(
            logger,
            "generation_run_launcher.succeeded run_id=%s",
            claimed.run.id,
        )

    async def _record_success_events_and_costs(
        self,
        uow: CanonicalUnitOfWork,
        claimed: ClaimedRun,
        result: DraftScriptResult,
        persisted_tei: PersistedTei,
    ) -> None:
        """Record success-side events, costs, and terminal status."""
        await uow.generation_runs.append_event(
            claimed.run.id,
            kind="tei.persisted",
            payload={
                "tei_revision": persisted_tei.revision,
                "content_hash": persisted_tei.content_hash,
                "qa_status": QaStatus.SKIPPED.value,
            },
            occurred_at=self.clock(),
        )
        await self._record_costs(uow, claimed.run.id, result)
        await uow.generation_runs.append_event(
            claimed.run.id,
            kind="run.succeeded",
            payload={"current_node": "complete"},
            occurred_at=self.clock(),
        )
        await uow.generation_runs.update_run_status(
            claimed.run.id,
            update=GenerationRunStatusUpdate(
                status=GenerationRunStatus.SUCCEEDED,
                current_node=None,
                ended_at=self.clock(),
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

    async def _record_failure(self, run_id: uuid.UUID, failure: Failure) -> None:
        """Record a terminal failed run state."""
        async with self.uow_factory() as uow:
            try:
                await self._append_failure_events(uow, run_id, failure)
                await uow.generation_runs.update_run_status(
                    run_id,
                    update=GenerationRunStatusUpdate(
                        status=GenerationRunStatus.FAILED,
                        current_node=None,
                        ended_at=self.clock(),
                        error_message=failure.message,
                        error_category=failure.category,
                    ),
                )
                await uow.commit()
            except RunAlreadyTerminal, RunNotFound:
                await uow.rollback()
                return
        self._record_terminal_metric(GenerationRunStatus.FAILED, failure.category)
        self.metrics.increment_counter(
            _METRIC_DRAFT_ERRORS,
            labels={"error_category": failure.category},
        )
        log_error(
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
