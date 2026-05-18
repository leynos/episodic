"""Tests for StructuredPlanningOrchestrator."""

import pytest

from episodic.orchestration import (
    ActionExecutionResult,
    ActionKind,
    ModelTier,
    PlannedAction,
    RoutingToolExecutor,
    StructuredGenerationPlanner,
    StructuredPlanningOrchestrator,
    ToolExecutionError,
)
from tests._orchestration_fakes import (
    _config,
    _FakeLLMPort,
    _FakeToolExecutor,
    _plan_payload,
    _request,
    _response,
    _usage,
)


@pytest.mark.asyncio
async def test_orchestrator_dispatches_through_tool_port() -> None:
    """Orchestrator should execute planned actions via the tool port only."""
    llm = _FakeLLMPort([
        _response(
            _plan_payload(),
            model="gpt-4.1",
            usage=_usage(input_tokens=20, output_tokens=10),
        )
    ])
    planner = StructuredGenerationPlanner(llm=llm, config=_config())
    tool_result = ActionExecutionResult(
        action_id="action-1",
        action_kind=ActionKind.GENERATE_SHOW_NOTES,
        model_tier=ModelTier.EXECUTION,
        model="gpt-4o-mini",
        summary="Generated one show-notes payload.",
        usage=_usage(input_tokens=12, output_tokens=8),
    )
    tool_executor = _FakeToolExecutor(result=tool_result)
    orchestrator = StructuredPlanningOrchestrator(
        planner=planner,
        tool_executor=tool_executor,
    )

    result = await orchestrator.orchestrate(_request())

    assert len(tool_executor.calls) == 1
    planned_action, context = tool_executor.calls[0]
    assert planned_action.action_kind is ActionKind.GENERATE_SHOW_NOTES
    assert context.correlation_id == "corr-123"
    assert result.action_results == (tool_result,)
    assert result.total_usage == _usage(input_tokens=32, output_tokens=18)


@pytest.mark.asyncio
async def test_orchestrator_propagates_tool_failures() -> None:
    """Tool errors should not be swallowed by the orchestration layer."""
    llm = _FakeLLMPort([
        _response(
            _plan_payload(),
            model="gpt-4.1",
            usage=_usage(input_tokens=20, output_tokens=10),
        )
    ])
    planner = StructuredGenerationPlanner(llm=llm, config=_config())
    tool_executor = _FakeToolExecutor(error=ToolExecutionError("tool exploded"))
    orchestrator = StructuredPlanningOrchestrator(
        planner=planner,
        tool_executor=tool_executor,
    )

    with pytest.raises(ToolExecutionError, match="tool exploded"):
        await orchestrator.orchestrate(_request())


@pytest.mark.asyncio
async def test_routing_tool_executor_dispatches_by_action_kind() -> None:
    """Routing executor should let one orchestration run support multiple tools."""
    show_notes_result = ActionExecutionResult(
        action_id="show-notes-1",
        action_kind=ActionKind.GENERATE_SHOW_NOTES,
        model_tier=ModelTier.EXECUTION,
        model="gpt-4o-mini",
        summary="Generated show notes.",
        usage=_usage(input_tokens=4, output_tokens=2),
    )
    guest_bios_result = ActionExecutionResult(
        action_id="guest-bios-1",
        action_kind=ActionKind.GENERATE_GUEST_BIOS,
        model_tier=ModelTier.EXECUTION,
        model="gpt-4o-mini",
        summary="Generated guest bios.",
        usage=_usage(input_tokens=6, output_tokens=3),
    )
    show_notes_executor = _FakeToolExecutor(result=show_notes_result)
    guest_bios_executor = _FakeToolExecutor(result=guest_bios_result)
    routing_executor = RoutingToolExecutor(
        routes={
            ActionKind.GENERATE_SHOW_NOTES: show_notes_executor,
            ActionKind.GENERATE_GUEST_BIOS: guest_bios_executor,
        }
    )
    request = _request()

    show_notes_action = PlannedAction(
        action_id="show-notes-1",
        action_kind=ActionKind.GENERATE_SHOW_NOTES,
        rationale="Need show notes.",
        model_tier=ModelTier.EXECUTION,
    )
    guest_bios_action = PlannedAction(
        action_id="guest-bios-1",
        action_kind=ActionKind.GENERATE_GUEST_BIOS,
        rationale="Need guest bios.",
        model_tier=ModelTier.EXECUTION,
    )

    assert (
        await routing_executor.execute(show_notes_action, request) == show_notes_result
    )
    assert (
        await routing_executor.execute(guest_bios_action, request) == guest_bios_result
    )
    assert show_notes_executor.calls == [(show_notes_action, request)]
    assert guest_bios_executor.calls == [(guest_bios_action, request)]
