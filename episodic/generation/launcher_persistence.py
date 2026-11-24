"""Persist generation-run outcomes: draft events, TEI, costs, and status.

:class:`GenerationRunPersistence` owns the write side of a generation run:
recording that a draft was generated, persisting the TEI and its success-side
events, recording provider costs when a cost recorder is configured, and
applying the immutable ``GenerationRunStatusUpdate`` command for both terminal
success and terminal failure. Its collaborators are explicit fields, so the
component can be constructed with fakes instead of a launcher's shared state.
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
from episodic.canonical.generation_run_ports import (
    UNCHANGED,
    GenerationRunStatusUpdate,
)
from episodic.cost.ports import BillingPeriodKey
from episodic.cost.pricing_snapshot import PricedService
from episodic.cost.recorder import CostProviderOperation
from episodic.generation.launcher_quality import QaOutcome, qa_result_payload
from episodic.generation.launcher_support import (
    Clock,
    CostRecorderFactory,
    PersistedTei,
    ProviderCallRecordRequest,
    draft_generated_payload,
    provider_call_record,
)
from episodic.logging import get_logger, log_info
from episodic.observability import NoopValueMetrics, ValueMetricsPort

if typ.TYPE_CHECKING:
    import collections.abc as cabc
    import uuid

    from episodic.canonical.unit_of_work_protocols import CanonicalUnitOfWork
    from episodic.generation.draft_script import DraftScriptResult
    from episodic.generation.launcher_support import ClaimedRun

_METRIC_TERMINAL_STATES = "generation_run_terminal_total"

logger = get_logger(__name__)


@dc.dataclass(frozen=True, slots=True)
class _SuccessOutcome:
    """The artefacts and QA status one successful transition records."""

    result: DraftScriptResult
    persisted_tei: PersistedTei
    qa: QaOutcome


class PersistenceRuntime(typ.Protocol):
    """Live persistence-stage collaborators consulted at their use sites.

    Properties rather than values keep the component's reads aligned with the
    pre-split launcher, which read each field when it reached that write.
    """

    @property
    def uow_factory(self) -> cabc.Callable[[], CanonicalUnitOfWork]:
        """Factory for the detached units of work used by each write."""

    @property
    def clock(self) -> Clock:
        """Clock for event timestamps and terminal transitions."""

    @property
    def cost_recorder_factory(self) -> CostRecorderFactory | None:
        """Factory that binds a cost recorder to a unit of work."""

    @property
    def provider_name(self) -> str:
        """Provider name recorded in pinned pricing and provider-call costs."""

    @property
    def provider_operation(self) -> str:
        """Provider operation recorded in pinned pricing and provider-call costs."""

    @property
    def metrics(self) -> ValueMetricsPort:
        """Sink for terminal-state and draft-error metrics."""


@dc.dataclass(frozen=True, slots=True)
class PersistenceContext:
    """Value-backed persistence runtime for direct construction and tests.

    Attributes
    ----------
    uow_factory : cabc.Callable[[], CanonicalUnitOfWork]
        Factory for the detached units of work used by each write.
    clock : Clock
        Clock for event timestamps and terminal transitions.
    cost_recorder_factory : CostRecorderFactory | None
        Factory that binds a cost recorder to a unit of work, or ``None`` to
        disable cost recording.
    provider_name : str
        Provider name recorded in pinned pricing and provider-call costs.
    provider_operation : str
        Provider operation recorded in pinned pricing and provider-call costs.
    metrics : ValueMetricsPort
        Sink for terminal-state and draft-error metrics.
    """

    uow_factory: cabc.Callable[[], CanonicalUnitOfWork]
    clock: Clock
    cost_recorder_factory: CostRecorderFactory | None = None
    provider_name: str = "openai"
    provider_operation: str = "chat_completions"
    metrics: ValueMetricsPort = dc.field(default_factory=NoopValueMetrics)


@dc.dataclass(slots=True)
class GenerationRunPersistence:
    """Persist draft, success, cost, and failure outcomes for a run.

    Attributes
    ----------
    runtime : PersistenceRuntime
        Live view of the persistence-stage collaborators.
    """

    runtime: PersistenceRuntime

    async def record_draft_generated(
        self,
        run_id: uuid.UUID,
        result: DraftScriptResult,
    ) -> None:
        """Record that draft generation returned a provider response.

        The method opens its own unit of work through ``uow_factory``, appends
        the ``draft.generated`` event with the injected clock's timestamp, and
        commits it. Unit-of-work, repository, or commit failures propagate to
        the caller.

        Parameters
        ----------
        run_id : uuid.UUID
            Identifier of the run that produced the draft.
        result : DraftScriptResult
            Generated draft whose provider metadata and usage form the event
            payload.
        """
        async with self.runtime.uow_factory() as uow:
            await uow.generation_runs.append_event(
                run_id,
                kind="draft.generated",
                payload=draft_generated_payload(result),
                occurred_at=self.runtime.clock(),
            )
            await uow.commit()

    async def persist_success(
        self,
        claimed: ClaimedRun,
        result: DraftScriptResult,
        *,
        qa: QaOutcome | None = None,
    ) -> None:
        """Persist generated TEI, cost records, and terminal success.

        The method opens its own unit of work. After the revision-guarded TEI
        update succeeds, it appends the success-side events, records costs,
        applies the terminal status, and commits. Episode revision conflicts,
        missing episodes, invalid draft TEI, cost-recording failures, and
        commit failures propagate to the caller. The terminal-success metric
        and success log are emitted only after the commit returns.

        Parameters
        ----------
        claimed : ClaimedRun
            Claimed run and the pre-persistence episode revision.
        result : DraftScriptResult
            Generated draft to persist and record as the run's outcome.
        qa : QaOutcome | None
            QA status and evaluations to record; ``None`` records a skipped
            no-QA draft.
        """
        outcome = qa or QaOutcome(QaStatus.SKIPPED, ())
        async with self.runtime.uow_factory() as uow:
            updated_episode = await persist_draft_script(
                uow,
                DraftScriptPersistenceRequest(
                    episode_id=claimed.run.episode_id,
                    generation_run_id=claimed.run.id,
                    result=result,
                    expected_revision=claimed.episode.tei_revision,
                    qa_status=outcome.status,
                    clock=self.runtime.clock,
                ),
            )
            await self._record_success_transition(
                uow,
                claimed,
                _SuccessOutcome(
                    result=result,
                    persisted_tei=PersistedTei(
                        revision=updated_episode.tei_revision,
                        content_hash=updated_episode.tei_content_hash,
                    ),
                    qa=outcome,
                ),
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
        claimed: ClaimedRun,
        outcome: _SuccessOutcome,
    ) -> None:
        """Record success-side events, costs, and terminal status."""
        result = outcome.result
        qa = outcome.qa
        persisted_tei = outcome.persisted_tei
        if qa.status is QaStatus.PASSED:
            await uow.generation_runs.append_event(
                claimed.run.id,
                kind="qa.result",
                payload=qa_result_payload(QualityVerdict.PASSED, qa.evaluations),
                occurred_at=self.runtime.clock(),
            )
        await uow.generation_runs.append_event(
            claimed.run.id,
            kind="tei.persisted",
            payload={
                "tei_revision": persisted_tei.revision,
                "content_hash": persisted_tei.content_hash,
                "qa_status": qa.status.value,
            },
            occurred_at=self.runtime.clock(),
        )
        await self.record_costs(uow, claimed.run.id, result)
        await uow.generation_runs.append_event(
            claimed.run.id,
            kind="run.succeeded",
            payload={"current_node": "complete"},
            occurred_at=self.runtime.clock(),
        )
        await uow.generation_runs.update_run_status(
            claimed.run.id,
            update=GenerationRunStatusUpdate(
                status=GenerationRunStatus.SUCCEEDED,
                current_node=None,
                ended_at=self.runtime.clock(),
                qa_status=(UNCHANGED if qa.status is QaStatus.SKIPPED else qa.status),
                claim_token=claimed.token.proof,
            ),
        )

    async def record_costs(
        self,
        uow: CanonicalUnitOfWork,
        run_id: uuid.UUID,
        result: DraftScriptResult,
    ) -> None:
        """Record provider-call and roll-up cost entries when configured."""
        if self.runtime.cost_recorder_factory is None:
            return
        recorder = self.runtime.cost_recorder_factory(uow)
        if recorder is None:
            return
        billing_period_key = BillingPeriodKey(self.runtime.clock().strftime("%Y-%m"))
        await recorder.pin_run_pricing(
            str(run_id),
            (
                CostProviderOperation(
                    service_kind=PricedService.LLM,
                    provider_name=self.runtime.provider_name,
                    model=result.model,
                    operation=self.runtime.provider_operation,
                ),
            ),
            billing_period_key,
        )
        await recorder.record_provider_call(
            provider_call_record(
                ProviderCallRecordRequest(
                    run_id=run_id,
                    provider_name=self.runtime.provider_name,
                    provider_operation=self.runtime.provider_operation,
                    billing_period_key=billing_period_key,
                    result=result,
                    recorded_at=self.runtime.clock(),
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
        self.runtime.metrics.increment_counter(
            _METRIC_TERMINAL_STATES,
            labels={"status": status.value, "error_category": error_category},
        )


__all__ = ["GenerationRunPersistence", "PersistenceContext", "PersistenceRuntime"]
