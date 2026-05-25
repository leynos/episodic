"""Shared strategies and fakes for orchestration property tests."""

import dataclasses as dc
import json
import string
import typing as typ

import hypothesis.strategies as st

from episodic.generation import ShowNotesResult
from episodic.llm import LLMUsage
from episodic.orchestration import (
    ActionExecutionResult,
    ActionKind,
    ExecutionPlan,
    GenerationOrchestrationRequest,
    ModelTier,
    PlannedAction,
    PlannerResult,
)

KNOWN_ACTION_KIND_STRINGS = {m.value for m in ActionKind}


@dc.dataclass(slots=True)
class GraphEventRecorder:
    """Collect explicitly injected graph-node events for ordering assertions."""

    events: list[str] = dc.field(default_factory=list)

    def record(self, event: str) -> None:
        """Append one observed graph-node event."""
        self.events.append(event)


class PropGraphPlanner:
    """Emit canned planner payloads for Hypothesis graph probes."""

    def __init__(
        self,
        *,
        result: PlannerResult,
        event_recorder: GraphEventRecorder | None = None,
    ) -> None:
        self._result = result
        self._event_recorder = event_recorder

    async def plan(self, request: GenerationOrchestrationRequest) -> PlannerResult:
        """Record the plan node when requested and return the canned result."""
        if not request.script_tei_xml.startswith("<TEI>"):
            msg = f"expected TEI input, got {request.script_tei_xml!r}"
            raise AssertionError(msg)
        if not request.correlation_id:
            msg = "expected non-empty correlation_id"
            raise AssertionError(msg)
        if self._event_recorder is not None:
            self._event_recorder.record("plan")
        return self._result


class PropGraphToolExecutor:
    """Emit canned tool payloads for Hypothesis graph probes."""

    def __init__(
        self,
        result: ActionExecutionResult,
        *,
        event_recorder: GraphEventRecorder | None = None,
    ) -> None:
        self._result = result
        self._event_recorder = event_recorder

    async def execute(
        self,
        action: PlannedAction,
        context: GenerationOrchestrationRequest,
    ) -> ActionExecutionResult:
        """Record the execute node when requested and return the canned result."""
        if not context.script_tei_xml.startswith("<TEI>"):
            msg = f"expected TEI input, got {context.script_tei_xml!r}"
            raise AssertionError(msg)
        if action.action_kind is not ActionKind.GENERATE_SHOW_NOTES:
            msg = f"expected show-notes action, got {action.action_kind!r}"
            raise AssertionError(msg)
        if self._event_recorder is not None:
            self._event_recorder.record("execute")
        return self._result


class PropShowNotesGenerator:
    """Return an empty show-notes result for model-tier boundary probes."""

    @staticmethod
    async def generate(
        script_tei_xml: str,
        *,
        template_structure: dict[str, object] | None = None,
    ) -> ShowNotesResult:
        """Return a minimal structured show-notes result."""
        if not script_tei_xml.startswith("<TEI>"):
            msg = f"expected TEI input, got {script_tei_xml!r}"
            raise AssertionError(msg)
        if template_structure is None:
            msg = "expected template structure"
            raise AssertionError(msg)
        return ShowNotesResult(
            entries=(),
            usage=LLMUsage(input_tokens=1, output_tokens=0, total_tokens=1),
            model="prop-exec-model",
            provider_response_id="prop-exec-response",
            finish_reason="stop",
        )


@dc.dataclass(frozen=True, slots=True)
class PropTokenInputs:
    """Bundled token-count inputs for LangGraph property tests."""

    planner_input: int
    planner_output: int
    action_input: int
    action_output: int


token_inputs_strategy: st.SearchStrategy[PropTokenInputs] = st.builds(
    PropTokenInputs,
    planner_input=st.integers(min_value=0, max_value=10_000),
    planner_output=st.integers(min_value=0, max_value=10_000),
    action_input=st.integers(min_value=0, max_value=10_000),
    action_output=st.integers(min_value=0, max_value=10_000),
)


@dc.dataclass(frozen=True, slots=True)
class PropStepKeyInputs:
    """Bundled workflow step identity inputs for idempotency key tests."""

    workflow_id: str
    workflow_type: str
    step_name: str
    action_id: str


step_key_inputs_strategy: st.SearchStrategy[PropStepKeyInputs] = st.builds(
    PropStepKeyInputs,
    workflow_id=st.text(
        min_size=1,
        max_size=32,
        alphabet=string.ascii_letters + string.digits + "-",
    ),
    workflow_type=st.text(
        min_size=1,
        max_size=32,
        alphabet=string.ascii_letters + string.digits + "_",
    ),
    step_name=st.text(
        min_size=1,
        max_size=32,
        alphabet=string.ascii_letters + string.digits + "_",
    ),
    action_id=st.text(
        min_size=1,
        max_size=32,
        alphabet=string.ascii_letters + string.digits + "-",
    ),
)

prop_text = st.text(
    min_size=1,
    max_size=32,
    alphabet=string.ascii_letters + string.digits + "-_ .",
).filter(lambda value: bool(value.strip()))


def _usage_from_counts(input_tokens: int, output_tokens: int) -> LLMUsage:
    """Build internally consistent LLM token usage counts."""
    return LLMUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=input_tokens + output_tokens,
    )


usage_strategy = st.builds(
    _usage_from_counts,
    input_tokens=st.integers(min_value=0, max_value=10_000),
    output_tokens=st.integers(min_value=0, max_value=10_000),
)

planned_action_strategy = st.builds(
    PlannedAction,
    action_id=prop_text,
    action_kind=st.just(ActionKind.GENERATE_SHOW_NOTES),
    rationale=prop_text,
    model_tier=st.just(ModelTier.EXECUTION),
    required_inputs=st.lists(prop_text, max_size=4).map(tuple),
)

execution_plan_strategy = st.builds(
    ExecutionPlan,
    plan_version=prop_text,
    selected_planning_model=prop_text,
    selected_execution_model=prop_text,
    steps=st.lists(planned_action_strategy, min_size=1, max_size=4).map(tuple),
)

planner_result_strategy = st.builds(
    PlannerResult,
    plan=execution_plan_strategy,
    usage=st.one_of(st.none(), usage_strategy),
    model=prop_text,
    provider_response_id=prop_text,
    finish_reason=st.one_of(st.none(), prop_text),
)

action_result_strategy = st.builds(
    ActionExecutionResult,
    action_id=prop_text,
    action_kind=st.just(ActionKind.GENERATE_SHOW_NOTES),
    model_tier=st.just(ModelTier.EXECUTION),
    model=prop_text,
    summary=prop_text,
    usage=st.one_of(st.none(), usage_strategy),
)


def valid_plan_object() -> dict[str, object]:
    """Return one valid raw planner object suitable for targeted corruption."""
    return {
        "plan_version": "1.0",
        "steps": [
            {
                "action_id": "action-1",
                "action_kind": ActionKind.GENERATE_SHOW_NOTES.value,
                "rationale": "Generate publication-ready show notes.",
                "model_tier": ModelTier.EXECUTION.value,
                "required_inputs": ["script_tei_xml", "template_structure"],
            }
        ],
    }


def invalid_plan_without_plan_version() -> str:
    """Return JSON for a plan object with the required version field omitted."""
    payload = valid_plan_object()
    payload = {key: value for key, value in payload.items() if key != "plan_version"}
    return json.dumps(payload)


def invalid_plan_with_top_level_field(field_name: str, value: object) -> str:
    """Return JSON for a plan object with one top-level field replaced."""
    return json.dumps(valid_plan_object() | {field_name: value})


def invalid_plan_with_step_field(field_name: str, value: object) -> str:
    """Return JSON for a plan object with one first-step field replaced."""
    step = typ.cast("list[dict[str, object]]", valid_plan_object()["steps"])[0]
    return json.dumps(valid_plan_object() | {"steps": [step | {field_name: value}]})


def invalid_plan_without_step_field(field_name: str) -> str:
    """Return JSON for a plan object with one required first-step field omitted."""
    step = typ.cast("list[dict[str, object]]", valid_plan_object()["steps"])[0]
    narrowed_step = {key: value for key, value in step.items() if key != field_name}
    return json.dumps(valid_plan_object() | {"steps": [narrowed_step]})


unknown_action_kind_values = st.one_of(
    st.none(),
    st.integers(),
    st.text(min_size=1, max_size=512).filter(
        lambda value: value.strip() not in {kind.value for kind in ActionKind}
    ),
)

unknown_model_tier_values = st.one_of(
    st.none(),
    st.integers(),
    st.text(min_size=1, max_size=512).filter(
        lambda value: value.strip() not in {tier.value for tier in ModelTier}
    ),
)

invalid_required_inputs_values = st.one_of(
    st.integers(),
    st.lists(
        st.one_of(st.none(), st.integers(), st.just("")),
        min_size=1,
        max_size=10,
    ),
)

PLANNER_FORMAT_ERROR_PATTERN = (
    r"plan_version must be a non-empty string"
    r"|steps must be a list"
    r"|step must be an object"
    r"|action_id must be a non-empty string"
    r"|action_kind must be a non-empty string"
    r"|action_kind must be one of: generate_show_notes"
    r"|rationale must be a non-empty string"
    r"|model_tier must be a non-empty string"
    r"|model_tier must be one of: planning, execution"
    r"|required_inputs must be a list of strings"
    r"|required_inputs must contain only non-empty strings"
)

invalid_plan_payloads = st.one_of(
    st.just(invalid_plan_without_plan_version()),
    st.sampled_from(("", " ", "\t")).map(
        lambda value: invalid_plan_with_top_level_field("plan_version", value)
    ),
    st.one_of(
        st.none(),
        st.integers(),
        st.text(max_size=512),
        st.dictionaries(st.text(min_size=1, max_size=4), st.integers(), max_size=2),
    ).map(lambda value: invalid_plan_with_top_level_field("steps", value)),
    st.one_of(st.none(), st.integers(), st.text(max_size=512)).map(
        lambda value: invalid_plan_with_top_level_field("steps", [value])
    ),
    st.just(invalid_plan_without_step_field("action_id")),
    st.sampled_from(("", " ", "\n")).map(
        lambda value: invalid_plan_with_step_field("action_id", value)
    ),
    unknown_action_kind_values.map(
        lambda value: invalid_plan_with_step_field("action_kind", value)
    ),
    st.sampled_from(("", " ", "\r\n")).map(
        lambda value: invalid_plan_with_step_field("rationale", value)
    ),
    unknown_model_tier_values.map(
        lambda value: invalid_plan_with_step_field("model_tier", value)
    ),
    invalid_required_inputs_values.map(
        lambda value: invalid_plan_with_step_field("required_inputs", value)
    ),
)
