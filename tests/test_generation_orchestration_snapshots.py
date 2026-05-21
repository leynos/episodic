"""Regression tests for typed generation orchestration serialisation.

This module gives CI a stable view of the wire-shaped DTOs produced by the
generation orchestration layer. Syrupy snapshots catch accidental structural
changes in `ExecutionPlan`, `GenerationOrchestrationResult`,
`ShowNotesEntry`, and `ShowNotesResult` serialisation, including plan version
metadata and action-kind representation.

The non-snapshot assertions in this file cover the DTO invariants that make the
snapshots meaningful: show-notes optional field normalisation, execution-plan
step validation, action-result aggregation validation, and usage-accounting
consistency in the canonical orchestration fixture.
"""

import dataclasses
import typing as typ

import hypothesis.strategies as st
import pytest
from hypothesis import given, settings
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
    entry = make_show_notes_entry()
    serialised = dataclasses.asdict(entry)
    assert serialised == snapshot

def test_show_notes_result_serialisation_snapshot(
    snapshot: SnapshotAssertion,
) -> None:
    """Snapshot nested show-note entries plus deterministic provider metadata."""
    result = make_show_notes_result()
    serialised = dataclasses.asdict(result)
    assert serialised == snapshot

def test_show_notes_entry_normalises_optional_locator() -> None:
    """Verify optional locator normalisation before snapshot serialisation."""
    entry = make_show_notes_entry(tei_locator="   ")

    assert entry.tei_locator is None

def test_show_notes_entry_rejects_non_iso8601_timestamp() -> None:
    """Verify invalid timestamps cannot enter show-note snapshot fixtures."""
    with pytest.raises(ValueError, match="timestamp"):
        make_show_notes_entry(timestamp="5:30")

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

@dataclasses.dataclass(frozen=True)
class _OrchestrationResultSpec:
    """Parameter object for building the canonical orchestration DTO graph."""

    rationale: str = "test"
    required_inputs: tuple[str, ...] = dataclasses.field(default_factory=tuple)
    action_summary: str = "test"
    action_usage: LLMUsage = dataclasses.field(
        default_factory=lambda: LLMUsage(10, 20, 30)
    )
    show_notes_result: ShowNotesResult | None = None
    planner_usage: LLMUsage = dataclasses.field(
        default_factory=lambda: LLMUsage(1, 2, 3)
    )
    total_usage: LLMUsage = dataclasses.field(
        default_factory=lambda: LLMUsage(11, 22, 33)
    )
def _make_orchestration_result(
    spec: _OrchestrationResultSpec | None = None,
) -> GenerationOrchestrationResult:
    """Build the canonical orchestration DTO graph used by snapshots."""
    if spec is None:
        spec = _OrchestrationResultSpec()
    planned = PlannedAction(
        action_id="a1",
        action_kind=ActionKind.GENERATE_SHOW_NOTES,
        rationale=spec.rationale,
        model_tier=ModelTier.EXECUTION,
        required_inputs=spec.required_inputs,
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
        summary=spec.action_summary,
        usage=spec.action_usage,
        show_notes_result=spec.show_notes_result,
    )
    return GenerationOrchestrationResult(
        plan=plan,
        action_results=(action_done,),
        planner_usage=spec.planner_usage,
        total_usage=spec.total_usage,
    )
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
    show_notes = make_show_notes_result(entries=(make_show_notes_entry(),))
    result = _make_orchestration_result(
        _OrchestrationResultSpec(
            rationale="Generate listener-facing notes from canonical TEI.",
            required_inputs=("script_tei_xml",),
            action_summary="Generated one show-notes entry.",
            action_usage=show_notes.usage,
            show_notes_result=show_notes,
            planner_usage=LLMUsage(input_tokens=12, output_tokens=8, total_tokens=20),
            total_usage=LLMUsage(input_tokens=52, output_tokens=33, total_tokens=85),
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

def test_generation_orchestration_fixture_totals_partial_usage_overrides() -> None:
    """Verify total usage is derived from whichever usage values callers supply."""
    result = _make_orchestration_result(
        _OrchestrationResultSpec(
            action_usage=LLMUsage(input_tokens=5, output_tokens=7, total_tokens=12),
            total_usage=LLMUsage(input_tokens=6, output_tokens=9, total_tokens=15),
        )
    )
    assert result.total_usage == LLMUsage(6, 9, 15)

@given(
    planner=st.tuples(
        st.integers(min_value=0, max_value=100_000),
        st.integers(min_value=0, max_value=100_000),
        st.integers(min_value=0, max_value=200_000),
    ),
    action=st.tuples(
        st.integers(min_value=0, max_value=100_000),
        st.integers(min_value=0, max_value=100_000),
        st.integers(min_value=0, max_value=200_000),
    ),
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
            total_usage=LLMUsage(
                input_tokens=planner[0] + action[0],
                output_tokens=planner[1] + action[1],
                total_tokens=planner[2] + action[2],
            ),
        )
    )
    assert result.total_usage == LLMUsage(
        input_tokens=planner[0] + action[0],
        output_tokens=planner[1] + action[1],
        total_tokens=planner[2] + action[2],
    )
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
