"""Property tests for orchestration graph usage rollups.

This module uses Hypothesis to exercise the relationships between planner DTOs,
action results, the LangGraph orchestration wrapper, and the shared
`build_generation_result` aggregation helper. The tests are useful because they
check token accounting invariants over many generated inputs, giving CI
coverage that example-based orchestration tests cannot provide.
"""

import dataclasses
import string

import hypothesis.strategies as st
import pytest
from hypothesis import given, settings

from episodic.llm import LLMUsage
from episodic.orchestration import (
    ActionExecutionResult,
    ActionKind,
    ExecutionPlan,
    GenerationGraphState,
    GenerationOrchestrationRequest,
    GenerationOrchestrationResult,
    ModelTier,
    PlannedAction,
    PlannerResult,
    build_generation_orchestration_graph,
    build_generation_result,
)
from tests._orchestration_property_support import (
    PropGraphPlanner,
    PropGraphToolExecutor,
    PropTokenInputs,
    token_inputs_strategy,
    usage_counts_strategy,
)


def _build_planner_and_action(
    tokens: PropTokenInputs,
    correlation_id: str,
) -> tuple[PlannerResult, list[ActionExecutionResult]]:
    """Build graph planner and action results for one token-input example."""
    del correlation_id
    planner_usage = LLMUsage(
        tokens.planner_input,
        tokens.planner_output,
        tokens.planner_input + tokens.planner_output,
    )
    tool_usage = LLMUsage(
        tokens.action_input,
        tokens.action_output,
        tokens.action_input + tokens.action_output,
    )
    planner_result = PlannerResult(
        plan=ExecutionPlan(
            plan_version="1.0",
            selected_planning_model="prop-plan-model",
            selected_execution_model="prop-exec-model",
            steps=(
                PlannedAction(
                    action_id="action-1",
                    action_kind=ActionKind.GENERATE_SHOW_NOTES,
                    rationale="prop graph rationale",
                    model_tier=ModelTier.EXECUTION,
                    required_inputs=("script_tei_xml",),
                ),
            ),
        ),
        usage=planner_usage,
        model="gpt-4.1",
        provider_response_id="prop-planner",
        finish_reason="stop",
    )
    action_result = ActionExecutionResult(
        action_id="action-1",
        action_kind=ActionKind.GENERATE_SHOW_NOTES,
        model_tier=ModelTier.EXECUTION,
        model="prop-exec-model",
        summary="prop graph synthesis",
        usage=tool_usage,
    )
    return planner_result, [action_result]


async def _run_graph_and_collect(
    planner_result: PlannerResult,
    actions: list[ActionExecutionResult],
    correlation_id: str,
) -> GenerationOrchestrationResult:
    """Run the graph and return its orchestration result."""
    graph = build_generation_orchestration_graph(
        planner=PropGraphPlanner(result=planner_result),
        tool_executor=PropGraphToolExecutor(result=actions[0]),
    )
    request = GenerationOrchestrationRequest(
        correlation_id=correlation_id,
        script_tei_xml=(
            "<TEI><text><body><p>Hypothesis-driven graph workload</p></body>"
            "</text></TEI>"
        ),
        template_structure=None,
    )
    state = await graph.ainvoke(GenerationGraphState(request=request))
    return state["orchestration_result"]


def _assert_usage_rollup(
    result: GenerationOrchestrationResult,
    planner_total: int,
    tool_total: int,
) -> None:
    """Assert that graph usage is non-negative and additive."""
    expected_total_tokens = planner_total + tool_total
    assert result.total_usage.total_tokens >= 0, (
        f"total_tokens should be >= 0, got {result.total_usage.total_tokens}"
    )
    assert result.total_usage.total_tokens == expected_total_tokens, (
        "expected_total_tokens mismatch: "
        f"expected {expected_total_tokens}, "
        f"got {result.total_usage.total_tokens}"
    )


@given(planner=usage_counts_strategy, action=usage_counts_strategy)
@settings(max_examples=50)
def test_build_generation_result_total_usage_property(
    planner: tuple[int, int, int],
    action: tuple[int, int, int],
) -> None:
    """Property test: generation results sum planner and action usage fields."""
    planner_result, actions = _build_planner_and_action(
        PropTokenInputs(
            planner_input=planner[0],
            planner_output=planner[1],
            action_input=action[0],
            action_output=action[1],
        ),
        "usage-property",
    )
    planner_result = dataclasses.replace(
        planner_result,
        usage=LLMUsage(*planner),
    )
    actions[0] = dataclasses.replace(actions[0], usage=LLMUsage(*action))

    result = build_generation_result(planner_result, tuple(actions))

    expected_usage = LLMUsage(
        planner[0] + action[0],
        planner[1] + action[1],
        planner[2] + action[2],
    )
    assert result.total_usage == expected_usage, (
        f"expected total usage {expected_usage!r}, got {result.total_usage!r}"
    )
    assert result.total_usage.total_tokens == (
        result.total_usage.input_tokens + result.total_usage.output_tokens
    ), f"expected internally consistent total usage, got {result.total_usage!r}"


@given(
    tokens=token_inputs_strategy,
    correlation_id=st.text(
        min_size=1,
        max_size=48,
        alphabet=string.ascii_letters + string.digits + "-",
    ),
)
@settings(max_examples=50)
@pytest.mark.asyncio
async def test_langgraph_total_tokens_non_negative(
    tokens: PropTokenInputs,
    correlation_id: str,
) -> None:
    """Property test: LangGraph rollups keep total token counts semiring-safe."""
    planner_result, actions = _build_planner_and_action(tokens, correlation_id)
    orchestration_result = await _run_graph_and_collect(
        planner_result,
        actions,
        correlation_id,
    )
    _assert_usage_rollup(
        orchestration_result,
        tokens.planner_input + tokens.planner_output,
        tokens.action_input + tokens.action_output,
    )
    assert orchestration_result.plan == planner_result.plan, (
        "planner_result mismatch: "
        f"expected {planner_result.plan}, got {orchestration_result.plan}"
    )
    assert orchestration_result.action_results[0].model == "prop-exec-model", (
        "action result model mismatch: "
        f"expected 'prop-exec-model', "
        f"got {orchestration_result.action_results[0].model}"
    )
