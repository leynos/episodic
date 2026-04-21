"""Unit tests for the structured generation LangGraph seam."""

import dataclasses as dc

import pytest

from episodic.llm import LLMUsage
from episodic.orchestration import (
    ActionExecutionResult,
    ActionKind,
    ExecutionPlan,
    GenerationOrchestrationRequest,
    ModelTier,
    PlannedAction,
    PlannerResult,
)
from episodic.orchestration.langgraph import (
    GenerationGraphState,
    _execute_node,
    _plan_node,
    build_generation_orchestration_graph,
)


@dc.dataclass(slots=True)
class _FakePlanner:
    """Return one canned planning result."""

    result: PlannerResult

    async def plan(
        self,
        request: GenerationOrchestrationRequest,
    ) -> PlannerResult:
        """Return the canned result after validating the request."""
        assert request.script_tei_xml.startswith("<TEI>")
        return self.result


@dc.dataclass(slots=True)
class _FakeToolExecutor:
    """Return one canned execution result."""

    result: ActionExecutionResult

    async def execute(
        self,
        action: PlannedAction,
        context: GenerationOrchestrationRequest,
    ) -> ActionExecutionResult:
        """Return the canned result after validating the action and context."""
        assert action.action_kind is ActionKind.GENERATE_SHOW_NOTES
        assert context.correlation_id == "corr-graph"
        return self.result


def _request() -> GenerationOrchestrationRequest:
    return GenerationOrchestrationRequest(
        correlation_id="corr-graph",
        script_tei_xml="<TEI><text><body><p>Graph request</p></body></text></TEI>",
    )


def _planner_result() -> PlannerResult:
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
    )


def _action_result() -> ActionExecutionResult:
    return ActionExecutionResult(
        action_id="action-1",
        action_kind=ActionKind.GENERATE_SHOW_NOTES,
        model_tier=ModelTier.EXECUTION,
        model="gpt-4o-mini",
        summary="Generated show notes.",
        usage=LLMUsage(input_tokens=10, output_tokens=4, total_tokens=14),
    )


@pytest.mark.asyncio
async def test_generation_graph_propagates_plan_and_results() -> None:
    """Graph should preserve typed plan and execution results end to end."""
    graph = build_generation_orchestration_graph(
        planner=_FakePlanner(_planner_result()),
        tool_executor=_FakeToolExecutor(_action_result()),
    )

    state = await graph.ainvoke(GenerationGraphState(request=_request()))

    planner_result = state["planner_result"]
    orchestration_result = state["orchestration_result"]
    assert planner_result.plan.selected_planning_model == "gpt-4.1"
    assert orchestration_result.total_usage.total_tokens == 38
    assert orchestration_result.action_results[0].model == "gpt-4o-mini"


@pytest.mark.asyncio
async def test_plan_node_requires_request() -> None:
    """Planning node should fail loudly when request state is missing."""
    with pytest.raises(KeyError, match="request"):
        await _plan_node(
            GenerationGraphState(),
            planner=_FakePlanner(_planner_result()),
        )


@pytest.mark.asyncio
async def test_execute_node_requires_planner_result() -> None:
    """Execution node should fail loudly when planning state is missing."""
    with pytest.raises(KeyError, match="planner_result"):
        await _execute_node(
            GenerationGraphState(request=_request()),
            tool_executor=_FakeToolExecutor(_action_result()),
        )
