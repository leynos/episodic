"""Cost-recording tests for the structured generation LangGraph seam."""

import dataclasses as dc
import typing as typ

import pytest

from episodic.cost.ports import CostLedgerEntryId, UsageSource
from episodic.llm import LLMUsage, ProviderCallUsage
from episodic.orchestration import (
    ActionExecutionResult,
    ActionKind,
    ExecutionPlan,
    GenerationGraphExtensions,
    GenerationGraphState,
    GenerationOrchestrationRequest,
    ModelTier,
    PlannedAction,
    PlannerResult,
    build_generation_orchestration_graph,
)

if typ.TYPE_CHECKING:
    from episodic.cost.recorder import ProviderCallRecord


@dc.dataclass(slots=True)
class _Planner:
    """Return one planner result with cost-accounting usage metadata."""

    result: PlannerResult

    async def plan(self, request: GenerationOrchestrationRequest) -> PlannerResult:
        """Return the canned planner result."""
        assert request.correlation_id == "corr-graph-cost", (
            f"unexpected correlation_id: {request.correlation_id!r}"
        )
        return self.result


@dc.dataclass(slots=True)
class _ToolExecutor:
    """Return one action result with cost-accounting usage metadata."""

    result: ActionExecutionResult

    async def execute(
        self,
        action: PlannedAction,
        context: GenerationOrchestrationRequest,
    ) -> ActionExecutionResult:
        """Return the canned tool result."""
        assert action.action_id == "action-1", (
            f"unexpected action_id: {action.action_id!r}"
        )
        assert context.correlation_id == "corr-graph-cost", (
            f"unexpected correlation_id: {context.correlation_id!r}"
        )
        return self.result


@dc.dataclass(slots=True)
class _RecordingCostRecorder:
    """Capture graph cost-recorder calls."""

    provider_calls: list[ProviderCallRecord] = dc.field(default_factory=list)
    finalized_runs: list[tuple[str, str | None]] = dc.field(default_factory=list)

    async def pin_run_pricing(
        self,
        workflow_run_id: str,
        providers: object,
        billing_period_key: object,
    ) -> None:
        """Accept pricing-pin requests for graph tests."""
        _ = (workflow_run_id, providers, billing_period_key)

    async def record_provider_call(
        self,
        record: ProviderCallRecord,
    ) -> CostLedgerEntryId:
        """Record a provider-call command."""
        self.provider_calls.append(record)
        return CostLedgerEntryId(f"cost-{len(self.provider_calls)}")

    async def finalize_run(
        self,
        workflow_run_id: str,
        workflow_node: str | None,
    ) -> CostLedgerEntryId:
        """Record run finalization."""
        self.finalized_runs.append((workflow_run_id, workflow_node))
        return CostLedgerEntryId("rollup")


def _provider_call_usage(provider_response_id: str) -> ProviderCallUsage:
    """Build provider usage metadata for graph cost tests."""
    return ProviderCallUsage(
        usage_metrics={"input_tokens": 3, "output_tokens": 2},
        usage_source=UsageSource.PROVIDER,
        usage_complete=True,
        provider_response_id=provider_response_id,
        finish_reason="stop",
        started_at="2026-06-04T12:00:00+00:00",
        latency_ms=10,
    )


def _request() -> GenerationOrchestrationRequest:
    """Build a graph request for cost tests."""
    return GenerationOrchestrationRequest(
        correlation_id="corr-graph-cost",
        script_tei_xml="<TEI><text><body><p>Graph request</p></body></text></TEI>",
    )


def _planner_result() -> PlannerResult:
    """Build a planner result with provider-call usage."""
    return PlannerResult(
        plan=ExecutionPlan(
            plan_version="1.0",
            selected_planning_model="gpt-4.1",
            selected_execution_model="gpt-4o-mini",
            steps=(
                PlannedAction(
                    action_id="action-1",
                    action_kind=ActionKind.GENERATE_SHOW_NOTES,
                    rationale="Need show notes.",
                    model_tier=ModelTier.EXECUTION,
                    required_inputs=("script_tei_xml",),
                ),
            ),
        ),
        usage=LLMUsage(input_tokens=15, output_tokens=9, total_tokens=24),
        model="gpt-4.1",
        provider_response_id="planner-1",
        finish_reason="stop",
        provider_call_usage=_provider_call_usage("planner-1"),
    )


def _action_result() -> ActionExecutionResult:
    """Build an action result with provider-call usage."""
    return ActionExecutionResult(
        action_id="action-1",
        action_kind=ActionKind.GENERATE_SHOW_NOTES,
        model_tier=ModelTier.EXECUTION,
        model="gpt-4o-mini",
        summary="Generated show notes.",
        usage=LLMUsage(input_tokens=10, output_tokens=4, total_tokens=14),
        provider_call_usage=_provider_call_usage("action-1"),
    )


@pytest.mark.asyncio
async def test_generation_graph_records_costs_on_direct_finish_path() -> None:
    """Graph cost recording should run after direct execution finishes."""
    planner_result = _planner_result()
    action_result = _action_result()
    assert planner_result.usage is not None, "planner result should carry token usage"
    assert action_result.usage is not None, "action result should carry token usage"
    expected_total = (
        planner_result.usage.total_tokens + action_result.usage.total_tokens
    )
    cost_recorder = _RecordingCostRecorder()
    graph = build_generation_orchestration_graph(
        planner=_Planner(planner_result),
        tool_executor=_ToolExecutor(action_result),
        extensions=GenerationGraphExtensions(cost_recorder=cost_recorder),
    )

    state = await graph.ainvoke(GenerationGraphState(request=_request()))

    assert state["orchestration_result"].total_usage.total_tokens == expected_total, (
        "orchestration result should aggregate planner and action token usage"
    )
    assert len(cost_recorder.provider_calls) == 2, (
        "graph should record one planner and one action provider call"
    )
    assert cost_recorder.finalized_runs == [
        ("corr-graph-cost", None),
    ], "graph should finalize the workflow run after direct execution"
    planner_record, action_record = cost_recorder.provider_calls
    assert planner_record.workflow_node == "planner", (
        "planner provider call should be attributed to the planner node"
    )
    assert action_record.workflow_node == "generate_show_notes", (
        "action provider call should be attributed to the show-notes node"
    )
