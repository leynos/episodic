"""Tests for StructuredGenerationPlanner."""

import json

import pytest

from episodic.llm import LLMProviderOperation
from episodic.orchestration import (
    ActionKind,
    ModelTier,
    PlannedAction,
    PlanningResponseFormatError,
    StructuredGenerationPlanner,
)
from tests._orchestration_fakes import (
    _config,
    _FakeLLMPort,
    _plan_payload,
    _request,
    _response,
    _usage,
)


@pytest.mark.asyncio
async def test_planner_returns_typed_plan_and_uses_planning_model() -> None:
    """Planner should decode JSON strictly and use configured planning fields."""
    llm = _FakeLLMPort([
        _response(
            _plan_payload(),
            model="gpt-4.1",
            usage=_usage(input_tokens=40, output_tokens=12),
        )
    ])
    planner = StructuredGenerationPlanner(llm=llm, config=_config())

    result = await planner.plan(_request())

    assert result.plan.plan_version == "1.0"
    assert result.plan.selected_planning_model == "gpt-4.1"
    assert result.plan.selected_execution_model == "gpt-4o-mini"
    assert result.plan.steps == (
        PlannedAction(
            action_id="action-1",
            action_kind=ActionKind.GENERATE_SHOW_NOTES,
            rationale="Generate publication-ready show notes.",
            model_tier=ModelTier.EXECUTION,
            required_inputs=("script_tei_xml", "template_structure"),
        ),
    )
    assert result.usage.total_tokens == 52

    request = llm.requests[0]
    assert request.model == "gpt-4.1"
    assert request.provider_operation == LLMProviderOperation.CHAT_COMPLETIONS
    assert "enabled_action_kinds" in request.prompt
    assert "script_tei_xml" in request.prompt


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("payload", "expected_match"),
    [
        ("not valid json", "valid JSON"),
        (json.dumps([]), "object"),
        (json.dumps({"plan_version": "1.0", "steps": [{}]}), "action_id"),
        (
            json.dumps({
                "plan_version": "1.0",
                "steps": [
                    {
                        "action_id": "a1",
                        "action_kind": "unknown",
                        "rationale": "Nope",
                        "model_tier": "execution",
                    }
                ],
            }),
            "action_kind",
        ),
        (
            json.dumps({
                "plan_version": "1.0",
                "steps": [
                    {
                        "action_id": "a1",
                        "action_kind": "generate_show_notes",
                        "rationale": "   ",
                        "model_tier": "execution",
                    }
                ],
            }),
            "rationale",
        ),
    ],
)
async def test_planner_rejects_malformed_structured_output(
    payload: str,
    expected_match: str,
) -> None:
    """Planner should fail fast on invalid structured responses."""
    llm = _FakeLLMPort([
        _response(
            payload, model="gpt-4.1", usage=_usage(input_tokens=30, output_tokens=5)
        )
    ])
    planner = StructuredGenerationPlanner(llm=llm, config=_config())

    with pytest.raises(PlanningResponseFormatError, match=expected_match):
        await planner.plan(_request())
