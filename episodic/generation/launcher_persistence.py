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
from episodic.canonical.generation_run_ports import UNCHANGED, GenerationRunStatusUpdate
from episodic.cost.ports import BillingPeriodKey
from episodic.cost.pricing_snapshot import PricedService
from episodic.cost.recorder import CostProviderOperation
from episodic.generation.launcher_quality import QaOutcome, qa_result_payload
from episodic.generation.launcher_support import (
    PersistedTei,
    ProviderCallRecordRequest,
    draft_generated_payload,
    provider_call_record,
)
from episodic.logging import get_logger, log_info

if typ.TYPE_CHECKING:
    import uuid

    from episodic.canonical.unit_of_work_protocols import CanonicalUnitOfWork
    from episodic.generation.draft_script import DraftScriptResult
    from episodic.generation.launcher_support import ClaimedRun

_METRIC_TERMINAL_STATES = "generation_run_terminal_total"
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
