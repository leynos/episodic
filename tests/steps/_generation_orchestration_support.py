"""Recording doubles for the structured generation orchestration steps."""

import dataclasses as dc
import typing as typ

from episodic.cost.ports import CostLedgerEntryId
from episodic.orchestration import ResumeWorkflowCommand

if typ.TYPE_CHECKING:
    from episodic.cost.ports import BillingPeriodKey
    from episodic.cost.recorder import CostProviderOperation, ProviderCallRecord
    from episodic.llm.ports import LLMPort, LLMRequest, LLMResponse
    from episodic.orchestration import ActionExecutionResult


@dc.dataclass(slots=True)
class RecordingLLMPort:
    """Capture the actual `LLMRequest` values before delegating."""

    wrapped: LLMPort
    requests: list[LLMRequest] = dc.field(default_factory=list)

    async def generate(self, request: LLMRequest) -> LLMResponse:
        """Record and forward the request."""
        self.requests.append(request)
        return await self.wrapped.generate(request)


@dc.dataclass(slots=True)
class BDDResumePort:
    """Return the action result supplied by the behavioural resume command."""

    async def resume(
        self,
        command: ResumeWorkflowCommand,
    ) -> ActionExecutionResult:
        """Return the externally supplied action result."""
        match command:
            case ResumeWorkflowCommand(result=result):
                return result
            case _:
                msg = f"unsupported resume command: {type(command).__name__}"
                raise TypeError(msg)


@dc.dataclass(slots=True)
class RecordingCostRecorder:
    """Capture orchestration cost-recorder calls for the BDD scenario."""

    pinned_providers: tuple[CostProviderOperation, ...] = ()
    pinned_billing_period_key: BillingPeriodKey | None = None
    provider_calls: list[ProviderCallRecord] = dc.field(default_factory=list)
    finalized_workflow_run_id: str | None = None

    async def pin_run_pricing(
        self,
        workflow_run_id: str,
        providers: tuple[CostProviderOperation, ...],
        billing_period_key: BillingPeriodKey,
    ) -> None:
        """Capture pricing pins selected for this workflow."""
        _ = workflow_run_id
        self.pinned_providers = providers
        self.pinned_billing_period_key = billing_period_key

    async def record_provider_call(
        self,
        record: ProviderCallRecord,
    ) -> CostLedgerEntryId:
        """Capture provider-call ledger input."""
        self.provider_calls.append(record)
        return CostLedgerEntryId(f"bdd:{record.idempotency_key}")

    async def finalize_run(
        self,
        workflow_run_id: str,
        workflow_node: str | None,
    ) -> CostLedgerEntryId:
        """Capture the final run-level roll-up request."""
        _ = workflow_node
        self.finalized_workflow_run_id = workflow_run_id
        return CostLedgerEntryId(f"bdd:run:{workflow_run_id}:rollup")
