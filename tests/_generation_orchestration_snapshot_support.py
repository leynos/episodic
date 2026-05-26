"""Shared fixtures for generation orchestration snapshot tests."""

import dataclasses
import typing as typ

from episodic.generation.show_notes import ShowNotesEntry, ShowNotesResult
from episodic.llm import LLMRequest, LLMResponse, LLMUsage
from episodic.orchestration import (
    ActionExecutionResult,
    ActionKind,
    ExecutionPlan,
    GenerationOrchestrationConfig,
    GenerationOrchestrationResult,
    ModelTier,
    PlannedAction,
    PlanningResponseFormatError,
    StructuredGenerationPlanner,
)


class _UnusedLLMPort:
    """LLM shim only required for constructing `StructuredGenerationPlanner`."""

    @staticmethod
    async def generate(request: LLMRequest) -> LLMResponse:
        """Unreachable for prompt-only assertions."""
        msg = (
            "StructuredGenerationPlanner.build_prompt snapshot harness must "
            f"never await generate ({request=!r})."
        )
        raise AssertionError(msg)


class _PlannedActionKwargs(typ.TypedDict):
    """Typed kwargs for planned-action validation probes."""

    action_id: str
    action_kind: ActionKind
    rationale: str
    model_tier: ModelTier
    required_inputs: tuple[str, ...]


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
    total_usage: LLMUsage | None = None


def _make_show_notes_entry(
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


def _make_show_notes_result(
    *,
    entries: tuple[ShowNotesEntry, ...] | None = None,
) -> ShowNotesResult:
    """Build the canonical show-notes result used by nested DTO snapshots."""
    if entries is None:
        entries = (
            _make_show_notes_entry(),
            _make_show_notes_entry(
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
    total_usage = spec.total_usage or LLMUsage(
        spec.planner_usage.input_tokens + spec.action_usage.input_tokens,
        spec.planner_usage.output_tokens + spec.action_usage.output_tokens,
        spec.planner_usage.total_tokens + spec.action_usage.total_tokens,
    )
    return GenerationOrchestrationResult(
        plan=plan,
        action_results=(action_done,),
        planner_usage=spec.planner_usage,
        total_usage=total_usage,
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
    if not isinstance(steps, list):
        msg = f"expected steps list in valid plan payload, got {steps!r}"
        raise TypeError(msg)
    step = steps[0]
    if not isinstance(step, dict):
        msg = f"expected step mapping in valid plan payload, got {step!r}"
        raise TypeError(msg)
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
