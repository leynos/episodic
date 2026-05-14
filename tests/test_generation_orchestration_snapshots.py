"""Syrupy regression snapshots for typed generation artefacts."""

import dataclasses
import typing as typ

from syrupy.assertion import SnapshotAssertion

from episodic.llm import LLMRequest, LLMResponse, LLMUsage
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
    PlanningResponseFormatError,
    StructuredGenerationPlanner,
)
from episodic.orchestration.langgraph import (
    _action_result_to_payload,
    _planner_result_to_payload,
)


class _UnusedLLMPort:
    """LLM shim only required for constructing `StructuredGenerationPlanner`."""

    async def generate(self, request: LLMRequest) -> LLMResponse:
        """Unreachable for prompt-only assertions."""
        msg = (
            "StructuredGenerationPlanner.build_prompt snapshot harness must "
            f"never await generate ({request=!r})."
        )
        raise RuntimeError(msg)


def _valid_plan_payload() -> dict[str, object]:
    """Return one raw planner payload used as the basis for error snapshots."""
    return {
        "plan_version": "1.0",
        "steps": [
            {
                "action_id": "action-1",
                "action_kind": ActionKind.GENERATE_SHOW_NOTES.value,
                "rationale": "Generate show notes.",
                "model_tier": ModelTier.EXECUTION.value,
                "required_inputs": ["script_tei_xml"],
            }
        ],
    }


def _valid_plan_step() -> dict[str, object]:
    """Return the first valid raw planner step for targeted corruption."""
    steps = _valid_plan_payload()["steps"]
    assert isinstance(steps, list)
    step = steps[0]
    assert isinstance(step, dict)
    return typ.cast("dict[str, object]", step)


def _plan_payload_with_step_field(field_name: str, value: object) -> dict[str, object]:
    """Return a planner payload with one step field replaced."""
    return _valid_plan_payload() | {"steps": [_valid_plan_step() | {field_name: value}]}


def _plan_payload_without_step_field(field_name: str) -> dict[str, object]:
    """Return a planner payload with one required step field omitted."""
    return _valid_plan_payload() | {
        "steps": [
            {
                key: value
                for key, value in _valid_plan_step().items()
                if key != field_name
            }
        ]
    }


def _capture_plan_format_error(payload: dict[str, object]) -> str:
    """Return the structured-planner format error for a malformed payload."""
    try:
        StructuredGenerationPlanner._parse_plan(
            payload,
            config=GenerationOrchestrationConfig(
                planning_model="gpt-4.1",
                execution_model="gpt-4o-mini",
            ),
        )
    except PlanningResponseFormatError as exc:
        return str(exc)
    msg = f"Expected PlanningResponseFormatError for payload: {payload!r}"
    raise AssertionError(msg)


def test_build_prompt_snapshot(snapshot: SnapshotAssertion) -> None:
    """Snapshot the JSON planner prompt rendered for a minimal request."""
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
    """Snapshot dataclass serialisation for execution plans."""
    planned = PlannedAction(
        action_id="a1",
        action_kind=ActionKind.GENERATE_SHOW_NOTES,
        rationale="test",
        model_tier=ModelTier.EXECUTION,
    )
    plan = ExecutionPlan(
        plan_version="1",
        selected_planning_model="gpt-4.1",
        selected_execution_model="gpt-4o-mini",
        steps=(planned,),
    )
    serialised = dataclasses.asdict(plan)
    assert serialised == snapshot


def test_generation_orchestration_result_snapshot(
    snapshot: SnapshotAssertion,
) -> None:
    """Snapshot dataclass serialisation for aggregated orchestration results."""
    planned = PlannedAction(
        action_id="a1",
        action_kind=ActionKind.GENERATE_SHOW_NOTES,
        rationale="test",
        model_tier=ModelTier.EXECUTION,
    )
    plan = ExecutionPlan(
        plan_version="1",
        selected_planning_model="gpt-4.1",
        selected_execution_model="gpt-4o-mini",
        steps=(planned,),
    )
    action_done = ActionExecutionResult(
        action_id="a1",
        action_kind=ActionKind.GENERATE_SHOW_NOTES,
        model_tier=ModelTier.EXECUTION,
        model="gpt-4o-mini",
        summary="test",
        usage=LLMUsage(input_tokens=10, output_tokens=20, total_tokens=30),
    )
    result = GenerationOrchestrationResult(
        plan=plan,
        action_results=(action_done,),
        planner_usage=LLMUsage(input_tokens=1, output_tokens=2, total_tokens=3),
        total_usage=LLMUsage(input_tokens=11, output_tokens=22, total_tokens=33),
    )
    serialised = dataclasses.asdict(result)
    assert serialised == snapshot


def test_checkpoint_payload_snapshot(snapshot: SnapshotAssertion) -> None:
    """Snapshot checkpoint payload conversion for planner and action results."""
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
