"""Structured planning orchestrator implementation."""

import dataclasses as dc
import datetime as dt
import time
import typing as typ

from episodic.cost.ports import BillingPeriodKey, IdempotencyKey, PricingModel
from episodic.cost.recorder import CostProviderOperation, ProviderCallRecord
from episodic.llm import LLMError

from ._types import (
    ActionKind,
    PlanningResponseFormatError,
    ToolExecutionError,
    UnsupportedActionError,
    _log_event,
)
from ._usage import build_generation_result

if typ.TYPE_CHECKING:
    import collections.abc as cabc

    from episodic.llm import ProviderCallUsage

    from ._dto import (
        ActionExecutionResult,
        ExecutionPlan,
        GenerationOrchestrationRequest,
        GenerationOrchestrationResult,
        PlannedAction,
        PlannerResult,
    )
    from ._protocols import CostRecorderPort, PlannerPort, ToolExecutorPort


_DEFAULT_PROVIDER_NAME = "openai"
_PLANNER_WORKFLOW_NODE = "planner"


@dc.dataclass(frozen=True, slots=True)
class _ProviderCallContext:
    """Stable context needed to build one cost-recorder command."""

    workflow_run_id: str
    workflow_node: str
    logical_call_id: str
    model: str
    operation: str


@dc.dataclass(slots=True)
class StructuredPlanningOrchestrator:
    """Plan one orchestration run, then execute each planned action in order."""

    planner: PlannerPort
    tool_executor: ToolExecutorPort
    cost_recorder: CostRecorderPort | None = None

    def _execute_single_action(
        self,
        action: PlannedAction,
        request: GenerationOrchestrationRequest,
        plan: ExecutionPlan,
    ) -> cabc.Awaitable[ActionExecutionResult]:
        """Execute one planned action with the standard action log envelope."""

        async def execute() -> ActionExecutionResult:
            _log_event(
                "debug",
                "structured_planning_orchestrator.execute_plan.action.start",
                correlation_id=request.correlation_id,
                action_id=action.action_id,
                action_kind=str(action.action_kind),
                execution_model=plan.selected_execution_model,
            )
            t0 = time.monotonic()
            try:
                result = await self.tool_executor.execute(action, request)
            except (LLMError, ToolExecutionError, UnsupportedActionError) as exc:
                _log_event(
                    "error",
                    "structured_planning_orchestrator.execute_plan.action.error",
                    correlation_id=request.correlation_id,
                    action_id=action.action_id,
                    action_kind=str(action.action_kind),
                    execution_model=plan.selected_execution_model,
                    elapsed_ms=round((time.monotonic() - t0) * 1000, 1),
                    error_type=type(exc).__name__,
                    error=str(exc),
                )
                raise
            _log_event(
                "debug",
                "structured_planning_orchestrator.execute_plan.action.complete",
                correlation_id=request.correlation_id,
                action_id=action.action_id,
                action_kind=str(action.action_kind),
                execution_model=plan.selected_execution_model,
                elapsed_ms=round((time.monotonic() - t0) * 1000, 1),
            )
            return result

        return execute()

    async def execute_plan(
        self,
        *,
        request: GenerationOrchestrationRequest,
        plan: ExecutionPlan,
    ) -> tuple[ActionExecutionResult, ...]:
        """Execute each plan step sequentially through the tool-execution port."""
        results: list[ActionExecutionResult] = []
        for action in plan.steps:
            results.append(  # noqa: PERF401 - keep execution sequential and explicit.
                await self._execute_single_action(action, request, plan)
            )
        return tuple(results)

    async def _pin_cost_pricing(
        self,
        request: GenerationOrchestrationRequest,
        providers: tuple[CostProviderOperation, ...],
    ) -> BillingPeriodKey:
        """Pin pricing for the run when cost recording is configured."""
        billing_period_key = _current_billing_period_key()
        if self.cost_recorder is not None and providers:
            await self.cost_recorder.pin_run_pricing(
                request.correlation_id,
                providers,
                billing_period_key,
            )
        return billing_period_key

    async def _record_planner_cost(
        self,
        request: GenerationOrchestrationRequest,
        planner_result: PlannerResult,
        billing_period_key: BillingPeriodKey,
    ) -> None:
        """Record the planner provider call when usage metadata is available."""
        if self.cost_recorder is None or planner_result.provider_call_usage is None:
            return
        await self.cost_recorder.record_provider_call(
            _provider_call_record(
                context=_ProviderCallContext(
                    workflow_run_id=request.correlation_id,
                    workflow_node=_PLANNER_WORKFLOW_NODE,
                    logical_call_id=planner_result.provider_response_id,
                    model=planner_result.model,
                    operation=str(planner_result.provider_operation),
                ),
                provider_call_usage=planner_result.provider_call_usage,
                billing_period_key=billing_period_key,
            )
        )

    async def _record_action_costs(
        self,
        request: GenerationOrchestrationRequest,
        action_results: tuple[ActionExecutionResult, ...],
        billing_period_key: BillingPeriodKey,
    ) -> None:
        """Record provider calls for action results that expose usage details."""
        if self.cost_recorder is None:
            return
        for action_result in action_results:
            if action_result.provider_call_usage is None:
                continue
            await self.cost_recorder.record_provider_call(
                _provider_call_record(
                    context=_ProviderCallContext(
                        workflow_run_id=request.correlation_id,
                        workflow_node=action_result.action_kind.value,
                        logical_call_id=action_result.action_id,
                        model=action_result.model,
                        operation=str(action_result.provider_operation),
                    ),
                    provider_call_usage=action_result.provider_call_usage,
                    billing_period_key=billing_period_key,
                )
            )

    async def _finalize_cost_recording(
        self,
        request: GenerationOrchestrationRequest,
    ) -> None:
        """Write the final roll-up when cost recording is configured."""
        if self.cost_recorder is not None:
            await self.cost_recorder.finalize_run(request.correlation_id, None)

    def _log_orchestrate_error(  # noqa: PLR6301 - keep orchestration log helper on the instance.
        self,
        exc: Exception,
        *,
        correlation_id: str,
        stage: str,
    ) -> None:
        """Emit the standard orchestration-stage error event."""
        _log_event(
            "error",
            "structured_planning_orchestrator.orchestrate.error",
            correlation_id=correlation_id,
            stage=stage,
            error_type=type(exc).__name__,
            error=str(exc),
        )

    def _run_planner(
        self,
        request: GenerationOrchestrationRequest,
    ) -> cabc.Awaitable[PlannerResult]:
        """Run the planner with the orchestration-level error log envelope."""

        async def run() -> PlannerResult:
            try:
                return await self.planner.plan(request)
            except (LLMError, PlanningResponseFormatError) as exc:
                self._log_orchestrate_error(
                    exc,
                    correlation_id=request.correlation_id,
                    stage="plan",
                )
                raise

        return run()

    def _run_execute_plan(
        self,
        request: GenerationOrchestrationRequest,
        plan: ExecutionPlan,
    ) -> cabc.Awaitable[tuple[ActionExecutionResult, ...]]:
        """Run tool execution with the orchestration-level error log envelope."""

        async def run() -> tuple[ActionExecutionResult, ...]:
            try:
                return await self.execute_plan(
                    request=request,
                    plan=plan,
                )
            except (LLMError, ToolExecutionError, UnsupportedActionError) as exc:
                self._log_orchestrate_error(
                    exc,
                    correlation_id=request.correlation_id,
                    stage="execute_plan",
                )
                raise

        return run()

    async def orchestrate(
        self,
        request: GenerationOrchestrationRequest,
    ) -> GenerationOrchestrationResult:
        """Plan and execute one structured generation request."""
        _log_event(
            "info",
            "structured_planning_orchestrator.orchestrate.start",
            correlation_id=request.correlation_id,
        )
        planner_result = await self._run_planner(request)
        providers = _cost_provider_operations(planner_result)
        billing_period_key = await self._pin_cost_pricing(request, providers)
        await self._record_planner_cost(request, planner_result, billing_period_key)
        action_results = await self._run_execute_plan(request, planner_result.plan)
        await self._record_action_costs(request, action_results, billing_period_key)
        result = build_generation_result(planner_result, action_results)
        await self._finalize_cost_recording(request)
        _log_event(
            "info",
            "structured_planning_orchestrator.orchestrate.complete",
            correlation_id=request.correlation_id,
            execution_model=planner_result.plan.selected_execution_model,
            input_tokens=result.total_usage.input_tokens,
            output_tokens=result.total_usage.output_tokens,
            total_tokens=result.total_usage.total_tokens,
        )
        return result


def _current_billing_period_key() -> BillingPeriodKey:
    """Return the current UTC billing period key."""
    return BillingPeriodKey(dt.datetime.now(dt.UTC).strftime("%Y-%m"))


def _cost_provider_operations(
    planner_result: PlannerResult,
) -> tuple[CostProviderOperation, ...]:
    """Return provider operations that must be priced for the run."""
    operations = {
        CostProviderOperation(
            provider_name=_DEFAULT_PROVIDER_NAME,
            model=planner_result.model,
            operation=str(planner_result.provider_operation),
        )
    }
    for step in planner_result.plan.steps:
        operation = CostProviderOperation(
            provider_name=_DEFAULT_PROVIDER_NAME,
            model=planner_result.plan.selected_execution_model,
            operation=str(step.action_kind),
        )
        if step.action_kind in {
            ActionKind.GENERATE_SHOW_NOTES,
            ActionKind.GENERATE_GUEST_BIOS,
        }:
            operation = CostProviderOperation(
                provider_name=_DEFAULT_PROVIDER_NAME,
                model=planner_result.plan.selected_execution_model,
                operation="chat_completions",
            )
        operations.add(operation)
    return tuple(sorted(operations, key=lambda item: (item.model, item.operation)))


def _provider_call_record(
    *,
    context: _ProviderCallContext,
    provider_call_usage: ProviderCallUsage,
    billing_period_key: BillingPeriodKey,
) -> ProviderCallRecord:
    """Build the recorder command for one provider call."""
    idempotency_key = IdempotencyKey(
        "run:"
        f"{context.workflow_run_id}:node:{context.workflow_node}:"
        f"call:{context.logical_call_id}:attempt:0"
    )
    return ProviderCallRecord(
        idempotency_key=idempotency_key,
        parent_cost_entry_id=None,
        provider_type="llm",
        provider_name=_DEFAULT_PROVIDER_NAME,
        model=context.model,
        workflow_node=context.workflow_node,
        operation=context.operation,
        usage=provider_call_usage.usage_metrics,
        usage_source=provider_call_usage.usage_source,
        usage_complete=provider_call_usage.usage_complete,
        pricing_model=PricingModel.PAYG,
        retry_attempt=0,
        billing_period_key=billing_period_key,
        workflow_run_id=context.workflow_run_id,
        recorded_at=provider_call_usage.started_at
        or dt.datetime.now(dt.UTC).isoformat(),
    )
