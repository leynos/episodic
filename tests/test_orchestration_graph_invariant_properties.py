"""Property tests for LangGraph orchestration invariants."""

import asyncio
import collections
import string

import hypothesis.strategies as st
import pytest
from hypothesis import given, settings

from episodic.llm import LLMUsage
from episodic.orchestration import (
    ActionExecutionResult,
    ActionKind,
    ExecutionPlan,
    GenerationGraphExtensions,
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


def _planner_result_from_tokens(tokens: PropTokenInputs) -> PlannerResult:
    """Build a planner result from generated token counts."""
    planner_usage = LLMUsage(
        tokens.planner_input,
        tokens.planner_output,
        tokens.planner_input + tokens.planner_output,
    )
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
        usage=planner_usage,
        model="gpt-4.1",
        provider_response_id="prop-planner",
        finish_reason="stop",
    )


def _action_result_from_tokens(tokens: PropTokenInputs) -> ActionExecutionResult:
    """Build an action result from generated token counts."""
    tool_usage = LLMUsage(
        tokens.action_input,
        tokens.action_output,
        tokens.action_input + tokens.action_output,
    )
    return ActionExecutionResult(
        action_id="action-1",
        action_kind=ActionKind.GENERATE_SHOW_NOTES,
        model_tier=ModelTier.EXECUTION,
        model="prop-exec-model",
        summary="prop graph synthesis",
        usage=tool_usage,
    )


def _assert_non_negative_usage(usage: LLMUsage, expected_total: int) -> None:
    """Assert non-negative token counts and the expected aggregate total."""
    assert usage.input_tokens >= 0, "usage.input_tokens count must be non-negative"
    assert usage.output_tokens >= 0, "usage.output_tokens count must be non-negative"
    assert usage.total_tokens >= 0, "usage.total_tokens count must be non-negative"
    assert usage.total_tokens == expected_total, "Expected values to match"


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
    planner_result = _planner_result_from_tokens(tokens)
    tool_result = _action_result_from_tokens(tokens)

    graph = build_generation_orchestration_graph(
        planner=PropGraphPlanner(result=planner_result),
        tool_executor=PropGraphToolExecutor(result=tool_result),
    )

    request = _request(correlation_id)
    state = await graph.ainvoke(GenerationGraphState(request=request))
    orchestration_result = state["orchestration_result"]
    expected_planner_total = tokens.planner_input + tokens.planner_output
    expected_tool_total = tokens.action_input + tokens.action_output
    expected_total_tokens = expected_planner_total + expected_tool_total
    _assert_non_negative_usage(orchestration_result.total_usage, expected_total_tokens)
    assert state["planner_result"] == planner_result, "Expected values to match"
    assert state["action_results"][0].model == "prop-exec-model", (
        "Expected values to match"
    )


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
        extensions=GenerationGraphExtensions(
            finish_callback=lambda _state: event_recorder.record("finish")
        ),
    )

    state = await graph.ainvoke(GenerationGraphState(request=request))

    assert event_recorder.events == ["plan", "execute", "finish"], (
        "Expected values to match"
    )
    assert state["planner_result"] is not None, "Expected value to be present"
    assert state["action_results"], "Expected condition to hold"
    assert state["orchestration_result"] is not None, "Expected value to be present"


async def _invoke_with_callback(
    *,
    checkpoint_port: InMemoryCheckpointStore | None = None,
) -> tuple[dict[str, object], list[GenerationOrchestrationResult]]:
    """Build a graph with a recording finish_callback and invoke it once.

    Returns the final graph state and the list of domain results the
    callback received, in invocation order.

    Returns
    -------
    tuple[dict[str, object], list[GenerationOrchestrationResult]]
        Result produced by the operation.
    """
    observed_results: list[GenerationOrchestrationResult] = []
    graph = build_generation_orchestration_graph(
        planner=PropGraphPlanner(result=_planner_result()),
        tool_executor=PropGraphToolExecutor(result=_tool_result()),
        extensions=GenerationGraphExtensions(
            checkpoint_port=checkpoint_port,
            finish_callback=observed_results.append,
        ),
    )
    state = await graph.ainvoke(GenerationGraphState(request=_request()))
    return state, observed_results


@pytest.mark.asyncio
async def test_finish_callback_is_invoked_in_direct_execute_path() -> None:
    """Direct execution invokes the finish callback with finished state."""
    state, observed_results = await _invoke_with_callback()

    assert len(observed_results) == 1, "Expected values to match"
    assert observed_results[0] is not None, "Expected value to be present"
    assert state["orchestration_result"] == observed_results[0], (
        "Expected values to match"
    )


@pytest.mark.asyncio
async def test_finish_callback_is_not_invoked_in_suspend_path() -> None:
    """Checkpointed execution stops before the finish callback hook."""
    state, observed_results = await _invoke_with_callback(
        checkpoint_port=InMemoryCheckpointStore()
    )

    assert not observed_results, "Expected condition to be false"
    assert isinstance(state["suspended_result"], SuspendedWorkflowResult), (
        "Expected value to have the required type"
    )
    assert state["orchestration_result"] is None, "Expected value to be absent"


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
        extensions=GenerationGraphExtensions(finish_callback=_raise_callback),
    )

    state = await graph.ainvoke(
        GenerationGraphState(request=_request("callback-error"))
    )

    assert state["orchestration_result"] is not None, "Expected value to be present"
    assert state["planner_result"] == planner_result, "Expected values to match"
    assert state["action_results"] == (tool_result,), "Expected values to match"


@pytest.mark.asyncio
async def test_finish_callback_records_concurrent_direct_results() -> None:
    """Concurrent direct execution invokes the shared finish callback once each."""
    expected_invocations = 4
    observed_results: list[GenerationOrchestrationResult] = []
    graph = build_generation_orchestration_graph(
        planner=PropGraphPlanner(result=_planner_result()),
        tool_executor=PropGraphToolExecutor(result=_tool_result()),
        extensions=GenerationGraphExtensions(finish_callback=observed_results.append),
    )

    states = await asyncio.gather(
        *(
            graph.ainvoke(
                GenerationGraphState(request=_request(f"callback-concurrent-{index}"))
            )
            for index in range(expected_invocations)
        )
    )

    assert len(observed_results) == expected_invocations, "Expected values to match"
    assert all(result is not None for result in observed_results), (
        "Expected value to be present"
    )
    assert collections.Counter(
        state["orchestration_result"] for state in states
    ) == collections.Counter(observed_results), (
        "Expected collection to contain the value"
    )
