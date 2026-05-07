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
    _finish_node,
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
        assert request.script_tei_xml.startswith("<TEI>"), (
            "expected script_tei_xml to start with '<TEI>', got: "
            f"{request.script_tei_xml!r}"
        )
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
        assert action.action_kind is ActionKind.GENERATE_SHOW_NOTES, (
            "expected action_kind to be GENERATE_SHOW_NOTES, got: "
            f"{action.action_kind!r}"
        )
        assert context.correlation_id == "corr-graph", (
            "expected correlation_id to be 'corr-graph', got: "
            f"{context.correlation_id!r}"
        )
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


class TestGenerationOrchestrationGraph:
    """Tests for the compiled generation orchestration graph."""

    @pytest.mark.asyncio
    async def test_generation_graph_propagates_plan_and_results(self) -> None:
        """Graph should preserve typed plan and execution results end to end."""
        graph = build_generation_orchestration_graph(
            planner=_FakePlanner(_planner_result()),
            tool_executor=_FakeToolExecutor(_action_result()),
        )

        state = await graph.ainvoke(GenerationGraphState(request=_request()))

        planner_result = state["planner_result"]
        orchestration_result = state["orchestration_result"]
        assert planner_result.plan.selected_planning_model == "gpt-4.1", (
            "expected selected_planning_model to be 'gpt-4.1', got: "
            f"{planner_result.plan.selected_planning_model!r}"
        )
        assert orchestration_result.total_usage.total_tokens == 38, (
            "expected total_usage.total_tokens to be 38, got: "
            f"{orchestration_result.total_usage.total_tokens!r}"
        )
        assert orchestration_result.action_results[0].model == "gpt-4o-mini", (
            "expected first action result model to be 'gpt-4o-mini', got: "
            f"{orchestration_result.action_results[0].model!r}"
        )


class TestLangGraphNodeValidation:
    """Tests for individual LangGraph node state validation."""

    @pytest.mark.asyncio
    async def test_plan_node_requires_request(self) -> None:
        """Planning node should fail loudly when request state is missing."""
        with pytest.raises(ValueError, match="missing required state value: request"):
            await _plan_node(
                GenerationGraphState(),
                planner=_FakePlanner(_planner_result()),
            )

    @pytest.mark.asyncio
    async def test_execute_node_requires_request(self) -> None:
        """Execution node should fail loudly when request state is missing."""
        with pytest.raises(ValueError, match="missing required state value: request"):
            await _execute_node(
                GenerationGraphState(planner_result=_planner_result()),
                tool_executor=_FakeToolExecutor(_action_result()),
            )

    @pytest.mark.asyncio
    async def test_execute_node_requires_planner_result(self) -> None:
        """Execution node should fail loudly when planning state is missing."""
        with pytest.raises(
            ValueError, match="missing required state value: planner_result"
        ):
            await _execute_node(
                GenerationGraphState(request=_request()),
                tool_executor=_FakeToolExecutor(_action_result()),
            )

    def test_finish_node_requires_request(self) -> None:
        """Finish node should fail loudly when request state is missing."""
        with pytest.raises(ValueError, match="missing required state value: request"):
            _finish_node(
                GenerationGraphState(
                    planner_result=_planner_result(),
                    action_results=(_action_result(),),
                ),
            )

    def test_finish_node_requires_planner_result(self) -> None:
        """Finish node should fail loudly when planning state is missing."""
        with pytest.raises(
            ValueError, match="missing required state value: planner_result"
        ):
            _finish_node(GenerationGraphState(request=_request()))
