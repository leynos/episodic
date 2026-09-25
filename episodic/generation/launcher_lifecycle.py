"""Persistence-side lifecycle transitions for generated draft runs."""

import dataclasses as dc
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
    ClaimedRun,
    Failure,
    PersistedTei,
    ProviderCallRecordRequest,
    draft_generated_payload,
    provider_call_record,
)
from episodic.logging import get_logger, log_error, log_info

if typ.TYPE_CHECKING:
    import collections.abc as cabc
    import uuid

    from episodic.canonical.unit_of_work_protocols import CanonicalUnitOfWork
    from episodic.generation.draft_script import DraftScriptResult
    from episodic.generation.launcher_support import Clock, CostRecorderFactory
    from episodic.observability import ValueMetricsPort


logger = get_logger(__name__)


@dc.dataclass(frozen=True, slots=True)
class _SuccessOutcome:
    """Persisted TEI details associated with one claimed provider result."""

    claimed: ClaimedRun
    result: DraftScriptResult
    persisted_tei: PersistedTei


class LifecycleContext(typ.Protocol):
    """Launcher dependencies used by durable lifecycle transitions."""

    uow_factory: cabc.Callable[[], CanonicalUnitOfWork]
    clock: Clock
    cost_recorder_factory: CostRecorderFactory | None
    provider_name: str
    provider_operation: str
    metrics: ValueMetricsPort

    def record_terminal_metric(
        self, status: GenerationRunStatus, error_category: str
    ) -> None:
        """Record the terminal-state counter through the owning launcher."""


async def record_draft_generated(
    context: LifecycleContext, run_id: uuid.UUID, result: DraftScriptResult
) -> None:
    """Append the durable event for a completed provider draft call."""
    async with context.uow_factory() as uow:
        await uow.generation_runs.append_event(
            run_id,
            kind="draft.generated",
            payload=draft_generated_payload(result),
            occurred_at=context.clock(),
        )
        await uow.commit()


async def persist_success(
    context: LifecycleContext, claimed: ClaimedRun, result: DraftScriptResult
) -> None:
    """Persist TEI, cost records, success events, and terminal status."""
    async with context.uow_factory() as uow:
        episode = await persist_draft_script(
            uow,
            DraftScriptPersistenceRequest(
                episode_id=claimed.run.episode_id,
                generation_run_id=claimed.run.id,
                result=result,
                expected_revision=claimed.episode.tei_revision,
                clock=context.clock,
            ),
        )
        await _record_success_events_and_costs(
            context,
            uow,
            _SuccessOutcome(
                claimed=claimed,
                result=result,
                persisted_tei=PersistedTei(
                    revision=episode.tei_revision,
                    content_hash=episode.tei_content_hash,
                ),
            ),
        )
        await uow.commit()
    context.record_terminal_metric(GenerationRunStatus.SUCCEEDED, "none")
    log_info(logger, "generation_run_launcher.succeeded run_id=%s", claimed.run.id)


async def record_failure(
    context: LifecycleContext, run_id: uuid.UUID, failure: Failure
) -> None:
    """Persist a terminal failure and its corresponding lifecycle events."""
    async with context.uow_factory() as uow:
        try:
            await _append_failure_events(context, uow, run_id, failure)
            await uow.generation_runs.update_run_status(
                run_id,
                update=GenerationRunStatusUpdate(
                    status=GenerationRunStatus.FAILED,
                    current_node="failed",
                    ended_at=context.clock(),
                    error_message=failure.message,
                    error_category=failure.category,
                ),
            )
            await uow.commit()
        except RunAlreadyTerminal, RunNotFound:
            await uow.rollback()
            return
    context.record_terminal_metric(GenerationRunStatus.FAILED, failure.category)
    context.metrics.increment_counter(
        "generation_run_draft_errors_total", labels={"error_category": failure.category}
    )
    log_error(
        logger,
        "generation_run_launcher.failed run_id=%s category=%s",
        run_id,
        failure.category,
    )


async def _record_success_events_and_costs(
    context: LifecycleContext,
    uow: CanonicalUnitOfWork,
    outcome: _SuccessOutcome,
) -> None:
    """Append success events, cost entries, and the terminal status update."""
    await uow.generation_runs.append_event(
        outcome.claimed.run.id,
        kind="tei.persisted",
        payload={
            "tei_revision": outcome.persisted_tei.revision,
            "content_hash": outcome.persisted_tei.content_hash,
            "qa_status": QaStatus.SKIPPED.value,
        },
        occurred_at=context.clock(),
    )
    await _record_costs(context, uow, outcome.claimed.run.id, outcome.result)
    await uow.generation_runs.append_event(
        outcome.claimed.run.id,
        kind="run.succeeded",
        payload={"current_node": "complete"},
        occurred_at=context.clock(),
    )
    await uow.generation_runs.update_run_status(
        outcome.claimed.run.id,
        update=GenerationRunStatusUpdate(
            status=GenerationRunStatus.SUCCEEDED,
            current_node="complete",
            ended_at=context.clock(),
        ),
    )


async def _record_costs(
    context: LifecycleContext,
    uow: CanonicalUnitOfWork,
    run_id: uuid.UUID,
    result: DraftScriptResult,
) -> None:
    """Record provider-call and roll-up cost entries when configured."""
    if context.cost_recorder_factory is None:
        return
    recorder = context.cost_recorder_factory(uow)
    if recorder is None:
        return
    billing_period_key = BillingPeriodKey(context.clock().strftime("%Y-%m"))
    await recorder.pin_run_pricing(
        str(run_id),
        (
            CostProviderOperation(
                provider_name=context.provider_name,
                model=result.model,
                operation=context.provider_operation,
            ),
        ),
        billing_period_key,
    )
    await recorder.record_provider_call(
        provider_call_record(
            ProviderCallRecordRequest(
                run_id=run_id,
                provider_name=context.provider_name,
                provider_operation=context.provider_operation,
                billing_period_key=billing_period_key,
                result=result,
                recorded_at=context.clock(),
            )
        )
    )
    await recorder.finalize_run(str(run_id), "draft")


async def _append_failure_events(
    context: LifecycleContext,
    uow: CanonicalUnitOfWork,
    run_id: uuid.UUID,
    failure: Failure,
) -> None:
    """Append any invalid-TEI and terminal failure events."""
    if failure.should_emit_invalid_tei:
        await uow.generation_runs.append_event(
            run_id,
            kind="tei.invalid",
            payload={"error_category": failure.category},
            occurred_at=context.clock(),
        )
    await uow.generation_runs.append_event(
        run_id,
        kind="run.failed",
        payload={"error_message": failure.message, "error_category": failure.category},
        occurred_at=context.clock(),
    )
