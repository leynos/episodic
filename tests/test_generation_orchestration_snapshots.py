"""Syrupy regression snapshots for structured generation orchestration.

Issue #72 added property coverage for orchestration invariants; this module
keeps stable snapshots alongside `tests/test_orchestration_properties.py` and
the focused orchestration unit tests. The snapshots pin the planner prompt,
execution-plan and orchestration-result serialisation, checkpoint payload
conversion, and representative planner-format error messages.
"""

import dataclasses
import typing as typ

from syrupy.assertion import SnapshotAssertion

from episodic.generation.show_notes import ShowNotesEntry, ShowNotesResult
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

def make_show_notes_entry(
    *,
    topic: str = "Structured planning",
    summary: str = "The episode explains typed orchestration DTOs.",
    timestamp: str | None = "PT5M30S",
    tei_locator: str | None = "#segment-structured-planning",
) -> ShowNotesEntry:
    """Build the canonical show-notes entry used by serialisation snapshots."""
    return ShowNotesEntry(
        topic=topic,
        summary=summary,
        timestamp=timestamp,
        tei_locator=tei_locator,
    )

def make_show_notes_result(
    *,
    entries: tuple[ShowNotesEntry, ...] | None = None,
) -> ShowNotesResult:
    """Build the canonical show-notes result used by nested DTO snapshots."""
    if entries is None:
        entries = (
            make_show_notes_entry(),
            make_show_notes_entry(
                topic="Snapshot coverage",
                summary="The episode covers regression snapshots for DTO output.",
                timestamp=None,
                tei_locator=None,
            ),
        )
    return ShowNotesResult(
        entries=entries,
        usage=LLMUsage(input_tokens=40, output_tokens=25, total_tokens=65),
        model="gpt-4o-mini",
        provider_response_id="show-notes-001",
        finish_reason="stop",
    )


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
    entry = make_show_notes_entry()
    serialised = dataclasses.asdict(entry)
    assert serialised == snapshot

def test_show_notes_result_serialisation_snapshot(
    snapshot: SnapshotAssertion,
) -> None:
    result = make_show_notes_result()
    serialised = dataclasses.asdict(result)
    assert serialised == snapshot

def _make_orchestration_result(
    *,
    rationale: str = "test",
    required_inputs: tuple[str, ...] = (),
    action_summary: str = "test",
    action_usage: LLMUsage | None = None,
    show_notes_result: ShowNotesResult | None = None,
    planner_usage: LLMUsage | None = None,
    total_usage: LLMUsage | None = None,
) -> GenerationOrchestrationResult:
    if action_usage is None:
        action_usage = LLMUsage(
            input_tokens=10,
            output_tokens=20,
            total_tokens=30,
        )
    if planner_usage is None:
        planner_usage = LLMUsage(
            input_tokens=1,
            output_tokens=2,
            total_tokens=3,
        )
    if total_usage is None:
        total_usage = LLMUsage(
            input_tokens=11,
            output_tokens=22,
            total_tokens=33,
        )
    planned = PlannedAction(
        action_id="a1",
        action_kind=ActionKind.GENERATE_SHOW_NOTES,
        rationale=rationale,
        model_tier=ModelTier.EXECUTION,
        required_inputs=required_inputs,
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
        summary=action_summary,
        usage=action_usage,
        show_notes_result=show_notes_result,
    )
    return GenerationOrchestrationResult(
        plan=plan,
        action_results=(action_done,),
        planner_usage=planner_usage,
        total_usage=total_usage,
    )
def test_generation_orchestration_result_snapshot(
    snapshot: SnapshotAssertion,
) -> None:
    result = _make_orchestration_result()
    assert dataclasses.asdict(result) == snapshot

def test_generation_orchestration_result_with_show_notes_snapshot(
    snapshot: SnapshotAssertion,
) -> None:
    show_notes = make_show_notes_result(entries=(make_show_notes_entry(),))
    result = _make_orchestration_result(
        rationale="Generate listener-facing notes from canonical TEI.",
        required_inputs=("script_tei_xml",),
        action_summary="Generated one show-notes entry.",
        action_usage=show_notes.usage,
        show_notes_result=show_notes,
        planner_usage=LLMUsage(input_tokens=12, output_tokens=8, total_tokens=20),
        total_usage=LLMUsage(input_tokens=52, output_tokens=33, total_tokens=85),
    )
    assert dataclasses.asdict(result) == snapshot
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
