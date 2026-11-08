"""Behaviour tests for the routing tool executor.

These tests document how `RoutingToolExecutor` dispatches planned actions to
the tool executor registered for their action kind, and that it rejects route
keys that normalize to the same action kind.
"""

import pytest

from episodic.orchestration import (
    ActionExecutionResult,
    ActionKind,
    ModelTier,
    PlannedAction,
    RoutingToolExecutor,
)
from tests._orchestration_fakes import _FakeToolExecutor, _request, _usage

_MATCH = "values should match"


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
    ), "show-notes action should route to the show-notes executor"
    assert (
        await routing_executor.execute(guest_bios_action, request) == guest_bios_result
    ), "guest-bios action should route to the guest-bios executor"
    assert show_notes_executor.calls == [(show_notes_action, request)], _MATCH
    assert guest_bios_executor.calls == [(guest_bios_action, request)], _MATCH


def test_routing_tool_executor_rejects_normalized_action_kind_collisions() -> None:
    """Routing executor should not silently discard equivalent route keys."""
    first_executor = _FakeToolExecutor()
    second_executor = _FakeToolExecutor()

    with pytest.raises(ValueError, match="route action kind collision"):
        RoutingToolExecutor(
            routes={
                "generate_show_notes": first_executor,
                " generate_show_notes ": second_executor,
            }
        )
