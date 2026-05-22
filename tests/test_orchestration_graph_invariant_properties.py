"""Property tests for LangGraph orchestration invariants."""

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
    InMemoryCheckpointStore,
    ModelTier,
    PlannedAction,
    PlannerResult,
    SuspendedWorkflowResult,
    build_generation_orchestration_graph,
)
from tests._orchestration_property_support import (
    GraphEventRecorder,
    PropGraphPlanner,
    PropGraphToolExecutor,
    PropTokenInputs,
    token_inputs_strategy,
)


def _planner_result() -> PlannerResult:
    """Build a minimal planner result for graph callback probes."""
    return PlannerResult(
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
        usage=LLMUsage(input_tokens=1, output_tokens=1, total_tokens=2),
        model="prop-plan-model",
        provider_response_id="prop-planner",
        finish_reason="stop",
    )


def _tool_result() -> ActionExecutionResult:
    """Build a minimal action result for graph callback probes."""
    return ActionExecutionResult(
        action_id="action-1",
        action_kind=ActionKind.GENERATE_SHOW_NOTES,
        model_tier=ModelTier.EXECUTION,
        model="prop-exec-model",
        summary="prop graph synthesis",
        usage=LLMUsage(input_tokens=1, output_tokens=1, total_tokens=2),
    )


def _request(correlation_id: str = "callback-probe") -> GenerationOrchestrationRequest:
    """Build a minimal generation request for graph callback probes."""
    return GenerationOrchestrationRequest(
        correlation_id=correlation_id,
        script_tei_xml="<TEI><text><body><p>body</p></body></text></TEI>",
    )


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
    tool_result = ActionExecutionResult(
        action_id="action-1",
        action_kind=ActionKind.GENERATE_SHOW_NOTES,
        model_tier=ModelTier.EXECUTION,
        model="prop-exec-model",
        summary="prop graph synthesis",
        usage=tool_usage,
    )

    graph = build_generation_orchestration_graph(
        planner=PropGraphPlanner(result=planner_result),
        tool_executor=PropGraphToolExecutor(result=tool_result),
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
    orchestration_result = state["orchestration_result"]
    expected_total_tokens = planner_usage.total_tokens + tool_usage.total_tokens
    assert orchestration_result.total_usage.input_tokens >= 0
    assert orchestration_result.total_usage.output_tokens >= 0
    assert orchestration_result.total_usage.total_tokens >= 0
    assert orchestration_result.total_usage.total_tokens == expected_total_tokens
    assert state["planner_result"] == planner_result
    assert state["action_results"][0].model == "prop-exec-model"


@given(
    request=st.builds(
        GenerationOrchestrationRequest,
        correlation_id=st.text(
            min_size=1,
            max_size=48,
            alphabet=string.ascii_letters + string.digits + "-",
        ),
        script_tei_xml=st.text(
            min_size=1,
            max_size=80,
            alphabet=string.ascii_letters + string.digits + " .,_-",
        ).map(lambda body: f"<TEI><text><body><p>{body}</p></body></text></TEI>"),
        template_structure=st.one_of(
            st.none(),
            st.just({"sections": ["intro", "analysis"]}),
        ),
    )
)
@settings(max_examples=50)
@pytest.mark.asyncio
async def test_langgraph_respects_plan_execute_finish_order(
    request: GenerationOrchestrationRequest,
) -> None:
    """Property test: valid requests always traverse plan, execute, then finish."""
    event_recorder = GraphEventRecorder()
    planner = PropGraphPlanner(
        event_recorder=event_recorder,
        result=PlannerResult(
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
            usage=LLMUsage(input_tokens=1, output_tokens=1, total_tokens=2),
            model="prop-plan-model",
            provider_response_id="prop-planner",
            finish_reason="stop",
        ),
    )
    tool_executor = PropGraphToolExecutor(
        ActionExecutionResult(
            action_id="action-1",
            action_kind=ActionKind.GENERATE_SHOW_NOTES,
            model_tier=ModelTier.EXECUTION,
            model="prop-exec-model",
            summary="prop graph synthesis",
            usage=LLMUsage(input_tokens=1, output_tokens=1, total_tokens=2),
        ),
        event_recorder=event_recorder,
    )
    graph = build_generation_orchestration_graph(
        planner=planner,
        tool_executor=tool_executor,
        finish_callback=lambda _state: event_recorder.record("finish"),
    )

    state = await graph.ainvoke(GenerationGraphState(request=request))

    assert event_recorder.events == ["plan", "execute", "finish"]
    assert state["planner_result"] is not None
    assert state["action_results"]
    assert state["orchestration_result"] is not None


async def _invoke_with_callback(
    *,
    checkpoint_port: InMemoryCheckpointStore | None = None,
) -> tuple[dict[str, object], list[GenerationOrchestrationResult]]:
    """Build a graph with a recording finish_callback and invoke it once.

    Returns the final graph state and the list of domain results the
    callback received, in invocation order.
    """
    observed_results: list[GenerationOrchestrationResult] = []
    graph = build_generation_orchestration_graph(
        planner=PropGraphPlanner(result=_planner_result()),
        tool_executor=PropGraphToolExecutor(result=_tool_result()),
        checkpoint_port=checkpoint_port,
        finish_callback=observed_results.append,
    )
    state = await graph.ainvoke(GenerationGraphState(request=_request()))
    return state, observed_results


@pytest.mark.asyncio
async def test_finish_callback_is_invoked_in_direct_execute_path() -> None:
    """Direct execution invokes the finish callback with finished state."""
    state, observed_results = await _invoke_with_callback()

    assert len(observed_results) == 1
    assert observed_results[0] is not None
    assert state["orchestration_result"] == observed_results[0]


@pytest.mark.asyncio
async def test_finish_callback_is_not_invoked_in_suspend_path() -> None:
    """Checkpointed execution stops before the finish callback hook."""
    state, observed_results = await _invoke_with_callback(
        checkpoint_port=InMemoryCheckpointStore()
    )

    assert not observed_results
    assert isinstance(state["suspended_result"], SuspendedWorkflowResult)
    assert state["orchestration_result"] is None


@pytest.mark.asyncio
async def test_langgraph_finish_callback_errors_do_not_replace_result() -> None:
    """Finish callback failures do not discard the computed graph result."""
    planner_result = _planner_result()
    tool_result = _tool_result()

    def _raise_callback(_result: GenerationOrchestrationResult) -> None:
        msg = "callback failed after result computation"
        raise RuntimeError(msg)

    graph = build_generation_orchestration_graph(
        planner=PropGraphPlanner(result=planner_result),
        tool_executor=PropGraphToolExecutor(result=tool_result),
        finish_callback=_raise_callback,
    )

    state = await graph.ainvoke(
        GenerationGraphState(request=_request("callback-error"))
    )

    assert state["orchestration_result"] is not None
    assert state["planner_result"] == planner_result
    assert state["action_results"] == (tool_result,)
