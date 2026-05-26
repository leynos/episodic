"""Regression tests for typed generation orchestration serialisation.

Syrupy snapshots give CI a stable view of orchestration DTO serialisation for
`ExecutionPlan`, `GenerationOrchestrationResult`, `ShowNotesEntry`, and
`ShowNotesResult`. Assertions also cover optional fields and usage accounting.
"""

import dataclasses
import typing as typ

import pytest
from hypothesis import given, settings
from syrupy.assertion import SnapshotAssertion

from episodic.llm import LLMUsage
from episodic.orchestration import (
    ActionExecutionResult,
    ActionKind,
    ExecutionPlan,
    GenerationOrchestrationConfig,
    GenerationOrchestrationRequest,
    GenerationOrchestrationResult,
    ModelTier,
    PlannedAction,
    PlannerResult,
    StructuredGenerationPlanner,
)
from episodic.orchestration.langgraph import (
    _action_result_to_payload,
    _planner_result_to_payload,
)
from tests._generation_orchestration_snapshot_support import (
    _capture_plan_format_error,
    _make_orchestration_result,
    _make_show_notes_entry,
    _make_show_notes_result,
    _OrchestrationResultSpec,
    _plan_payload_with_step_field,
    _plan_payload_without_step_field,
    _PlannedActionKwargs,
    _UnusedLLMPort,
    _valid_plan_payload,
)
from tests._orchestration_property_support import usage_counts_strategy


def test_build_prompt_snapshot(snapshot: SnapshotAssertion) -> None:
    """Snapshot the planner prompt that describes orchestration output shape."""
    cfg = GenerationOrchestrationConfig(
        planning_model="gpt-4.1",
        execution_model="gpt-4o-mini",
    )
    planner = StructuredGenerationPlanner(llm=_UnusedLLMPort(), config=cfg)
    request = GenerationOrchestrationRequest(
        correlation_id="snap-001",
        script_tei_xml="<TEI><text>test</text></TEI>",
        template_structure=None,
    )
    assert planner.build_prompt(request) == snapshot


def test_execution_plan_serialisation_snapshot(snapshot: SnapshotAssertion) -> None:
    """Snapshot the canonical dictionary form of an `ExecutionPlan`."""
    planned = PlannedAction(
        action_id="a1",
        action_kind=ActionKind.GENERATE_SHOW_NOTES,
        rationale="test",
        model_tier=ModelTier.EXECUTION,
        required_inputs=("script_tei_xml",),
    )
    plan = ExecutionPlan(
        plan_version="1",
        selected_planning_model="gpt-4.1",
        selected_execution_model="gpt-4o-mini",
        steps=(planned,),
    )
    # `asdict` is the canonical nested DTO serialisation path under snapshot.
    serialised = dataclasses.asdict(plan)
    assert serialised == snapshot


def test_show_notes_entry_serialisation_snapshot(
    snapshot: SnapshotAssertion,
) -> None:
    """Snapshot the serialised shape of one representative show-note entry."""
    entry = _make_show_notes_entry()
    serialised = dataclasses.asdict(entry)
    assert serialised == snapshot


def test_show_notes_result_serialisation_snapshot(
    snapshot: SnapshotAssertion,
) -> None:
    """Snapshot nested show-note entries plus deterministic provider metadata."""
    result = _make_show_notes_result()
    serialised = dataclasses.asdict(result)
    assert serialised == snapshot


def test_show_notes_entry_normalises_optional_locator() -> None:
    """Verify optional locator normalisation before snapshot serialisation."""
    entry = _make_show_notes_entry(tei_locator="   ")

    assert entry.tei_locator is None


def test_show_notes_entry_rejects_non_iso8601_timestamp() -> None:
    """Verify invalid timestamps cannot enter show-note snapshot fixtures."""
    with pytest.raises(ValueError, match="timestamp"):
        _make_show_notes_entry(timestamp="5:30")


def test_execution_plan_freezes_and_validates_steps() -> None:
    """Verify plan steps are typed and immutable before nested serialisation."""
    planned = PlannedAction(
        action_id="a1",
        action_kind="generate_show_notes",
        rationale="test",
        model_tier="execution",
    )
    plan = ExecutionPlan(
        plan_version=" 1 ",
        selected_planning_model=" gpt-4.1 ",
        selected_execution_model=" gpt-4o-mini ",
        steps=typ.cast("tuple[PlannedAction, ...]", [planned]),
    )

    assert plan.plan_version == "1"
    assert plan.steps == (planned,)
    assert plan.steps[0].action_kind is ActionKind.GENERATE_SHOW_NOTES

    with pytest.raises(TypeError, match="steps\\[0\\]"):
        ExecutionPlan(
            plan_version="1",
            selected_planning_model="gpt-4.1",
            selected_execution_model="gpt-4o-mini",
            steps=typ.cast(
                "tuple[PlannedAction, ...]",
                ("not-a-planned-action",),
            ),
        )


@pytest.mark.parametrize(
    ("field_name", "field_value", "expected_match"),
    [
        ("rationale", "   ", "rationale must be a non-empty string"),
        (
            "required_inputs",
            ("   ",),
            "required_inputs must be a non-empty string",
        ),
    ],
)
def test_planned_action_snapshot_fixture_rejects_invalid_fields(
    field_name: str,
    field_value: object,
    expected_match: str,
) -> None:
    """Verify invalid planned-action fields cannot enter snapshot fixtures."""
    kwargs: _PlannedActionKwargs = {
        "action_id": "a1",
        "action_kind": ActionKind.GENERATE_SHOW_NOTES,
        "rationale": "test",
        "model_tier": ModelTier.EXECUTION,
        "required_inputs": ("script_tei_xml",),
    }
    if field_name == "rationale":
        kwargs["rationale"] = typ.cast("str", field_value)
    else:
        kwargs["required_inputs"] = typ.cast("tuple[str, ...]", field_value)

    with pytest.raises(ValueError, match=expected_match):
        PlannedAction(**kwargs)


def test_generation_orchestration_result_snapshot(
    snapshot: SnapshotAssertion,
) -> None:
    """Snapshot the aggregate orchestration result without tool-specific data."""
    result = _make_orchestration_result()
    assert dataclasses.asdict(result) == snapshot


def test_generation_orchestration_result_with_show_notes_snapshot(
    snapshot: SnapshotAssertion,
) -> None:
    """Snapshot orchestration aggregation with nested show-note tool output."""
    show_notes = _make_show_notes_result(entries=(_make_show_notes_entry(),))
    result = _make_orchestration_result(
        _OrchestrationResultSpec(
            rationale="Generate listener-facing notes from canonical TEI.",
            required_inputs=("script_tei_xml",),
            action_summary="Generated one show-notes entry.",
            action_usage=show_notes.usage,
            show_notes_result=show_notes,
            planner_usage=LLMUsage(input_tokens=12, output_tokens=8, total_tokens=20),
        )
    )
    assert dataclasses.asdict(result) == snapshot


def test_generation_orchestration_result_freezes_action_results() -> None:
    """Verify aggregation rejects non-action results and freezes valid ones."""
    result = GenerationOrchestrationResult(
        plan=ExecutionPlan(
            plan_version="1",
            selected_planning_model="gpt-4.1",
            selected_execution_model="gpt-4o-mini",
            steps=(),
        ),
        action_results=typ.cast("tuple[ActionExecutionResult, ...]", []),
        planner_usage=None,
        total_usage=LLMUsage(input_tokens=0, output_tokens=0, total_tokens=0),
    )

    assert not result.action_results

    with pytest.raises(TypeError, match="action_results\\[0\\]"):
        GenerationOrchestrationResult(
            plan=result.plan,
            action_results=typ.cast(
                "tuple[ActionExecutionResult, ...]",
                ("not-an-action-result",),
            ),
            planner_usage=None,
            total_usage=result.total_usage,
        )


def test_generation_orchestration_fixture_preserves_usage_totals() -> None:
    """Verify the canonical aggregate keeps planner and action usage aligned."""
    result = _make_orchestration_result()
    action_usage = result.action_results[0].usage

    assert result.planner_usage is not None
    assert action_usage is not None
    expected_usage = LLMUsage(
        input_tokens=result.planner_usage.input_tokens + action_usage.input_tokens,
        output_tokens=result.planner_usage.output_tokens + action_usage.output_tokens,
        total_tokens=result.planner_usage.total_tokens + action_usage.total_tokens,
    )
    assert result.total_usage == expected_usage


@pytest.mark.parametrize(
    "spec",
    (  # noqa: PT007 - single-parameter values are clearer as direct specs here.
        _OrchestrationResultSpec(action_usage=LLMUsage(5, 7, 12)),
        _OrchestrationResultSpec(planner_usage=LLMUsage(5, 7, 12)),
    ),
)
def test_generation_orchestration_fixture_totals_partial_usage_overrides(
    spec: _OrchestrationResultSpec,
) -> None:
    """Verify total usage is derived from whichever usage values callers supply."""
    result = _make_orchestration_result(spec)
    assert result.total_usage == LLMUsage(
        spec.planner_usage.input_tokens + spec.action_usage.input_tokens,
        spec.planner_usage.output_tokens + spec.action_usage.output_tokens,
        spec.planner_usage.total_tokens + spec.action_usage.total_tokens,
    )


@given(
    planner=usage_counts_strategy,
    action=usage_counts_strategy,
)
@settings(max_examples=50)
def test_generation_orchestration_fixture_total_usage_property(
    planner: tuple[int, int, int],
    action: tuple[int, int, int],
) -> None:
    """Verify fixture total usage is a token-wise sum for arbitrary inputs."""
    planner_usage = LLMUsage(*planner)
    action_usage = LLMUsage(*action)
    result = _make_orchestration_result(
        _OrchestrationResultSpec(
            action_usage=action_usage,
            planner_usage=planner_usage,
        )
    )
    assert result.total_usage == LLMUsage(
        planner[0] + action[0],
        planner[1] + action[1],
        planner[2] + action[2],
    )
    assert result.total_usage.total_tokens == (
        result.total_usage.input_tokens + result.total_usage.output_tokens
    ), f"expected internally consistent total usage, got {result.total_usage!r}"


def test_checkpoint_payload_snapshot(snapshot: SnapshotAssertion) -> None:
    """Snapshot checkpoint payloads used when orchestration pauses and resumes."""
    planned = PlannedAction(
        action_id="a1",
        action_kind=ActionKind.GENERATE_SHOW_NOTES,
        rationale="test",
        model_tier=ModelTier.EXECUTION,
        required_inputs=("script_tei_xml",),
    )
    plan = ExecutionPlan(
        plan_version="1",
        selected_planning_model="gpt-4.1",
        selected_execution_model="gpt-4o-mini",
        steps=(planned,),
    )
    planner_result = PlannerResult(
        plan=plan,
        usage=LLMUsage(input_tokens=1, output_tokens=2, total_tokens=3),
        model="gpt-4.1",
        provider_response_id="planner-1",
        finish_reason="stop",
    )
    action_result = ActionExecutionResult(
        action_id="a1",
        action_kind=ActionKind.GENERATE_SHOW_NOTES,
        model_tier=ModelTier.EXECUTION,
        model="gpt-4o-mini",
        summary="test",
        usage=LLMUsage(input_tokens=10, output_tokens=20, total_tokens=30),
    )

    assert {
        "planner_result": _planner_result_to_payload(planner_result),
        "action_result": _action_result_to_payload(action_result),
    } == snapshot


def test_planner_format_error_messages_snapshot(snapshot: SnapshotAssertion) -> None:
    """Snapshot representative strict-planner format error messages."""
    assert {
        "missing_action_id": _capture_plan_format_error(
            _plan_payload_without_step_field("action_id")
        ),
        "missing_plan_version": _capture_plan_format_error({
            key: value
            for key, value in _valid_plan_payload().items()
            if key != "plan_version"
        }),
        "non_list_required_inputs": _capture_plan_format_error(
            _plan_payload_with_step_field("required_inputs", "script_tei_xml")
        ),
        "non_list_steps": _capture_plan_format_error(
            _valid_plan_payload() | {"steps": "not-a-list"}
        ),
        "non_object_step": _capture_plan_format_error(
            _valid_plan_payload() | {"steps": ["not-an-object"]}
        ),
        "unknown_action_kind": _capture_plan_format_error(
            _plan_payload_with_step_field("action_kind", "unknown_action")
        ),
        "unknown_model_tier": _capture_plan_format_error(
            _plan_payload_with_step_field("model_tier", "training")
        ),
    } == snapshot
