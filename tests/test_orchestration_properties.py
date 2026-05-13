"""Hypothesis property-based tests for orchestration invariants.

Issue #72 called out that the PR #69 orchestration suite had strong
deterministic unit coverage but lacked generative exploration of boundary
inputs. This module complements `test_orchestration_dto_validation.py`,
`test_orchestration_planner.py`, `test_show_notes_executor.py`, and
`test_generation_orchestration_langgraph.py` with property tests for enum
normalisation, model-tier validation, planner JSON error preservation, and the
LangGraph plan-execute-finish ordering contract.
"""

import dataclasses as dc
import json
import string
import typing as typ

import hypothesis.strategies as st
import pytest
from hypothesis import given, settings

from episodic.generation import ShowNotesResult
from episodic.llm import (
    LLMProviderOperation,
    LLMResponse,
    LLMUsage,
)
from episodic.orchestration import (
    ActionExecutionResult,
    ActionKind,
    ExecutionPlan,
    GenerationGraphState,
    GenerationOrchestrationConfig,
    GenerationOrchestrationRequest,
    ModelTier,
    PlannedAction,
    PlannerResult,
    PlanningResponseFormatError,
    ShowNotesToolExecutor,
    StructuredGenerationPlanner,
    UnsupportedActionError,
    WorkflowStepIdentity,
    build_generation_orchestration_graph,
    build_workflow_step_idempotency_key,
)
from episodic.orchestration.langgraph import (
    _action_result_from_payload,
    _action_result_to_payload,
    _plan_from_payload,
    _plan_to_payload,
    _planner_result_from_payload,
    _planner_result_to_payload,
)
from tests._orchestration_fakes import (
    _config,
    _FakeLLMPort,
    _request,
    _usage,
)

_ACTION_KIND_SAMPLES: tuple[ActionKind | str, ...] = tuple(ActionKind) + tuple(
    m.value for m in ActionKind
)
_KNOWN_ACTION_KIND_STRINGS = {m.value for m in ActionKind}


@dc.dataclass(slots=True)
class _GraphEventRecorder:
    """Collect explicitly injected graph-node events for ordering assertions."""

    events: list[str] = dc.field(default_factory=list)

    def record(self, event: str) -> None:
        """Append one observed graph-node event."""
        self.events.append(event)


class _PropGraphPlanner:
    """Emit canned planner payloads for Hypothesis graph probes."""

    def __init__(
        self,
        *,
        result: PlannerResult,
        event_recorder: _GraphEventRecorder | None = None,
    ) -> None:
        self._result = result
        self._event_recorder = event_recorder

    async def plan(self, request: GenerationOrchestrationRequest) -> PlannerResult:
        """Record the plan node when requested and return the canned result."""
        assert request.script_tei_xml.startswith("<TEI>"), (
            f"expected TEI input, got {request.script_tei_xml!r}"
        )
        assert request.correlation_id, "expected non-empty correlation_id"
        if self._event_recorder is not None:
            self._event_recorder.record("plan")
        return self._result


class _PropGraphToolExecutor:
    """Emit canned tool payloads for Hypothesis graph probes."""

    def __init__(
        self,
        result: ActionExecutionResult,
        *,
        event_recorder: _GraphEventRecorder | None = None,
    ) -> None:
        self._result = result
        self._event_recorder = event_recorder

    async def execute(
        self,
        action: PlannedAction,
        context: GenerationOrchestrationRequest,
    ) -> ActionExecutionResult:
        """Record the execute node when requested and return the canned result."""
        assert context.script_tei_xml.startswith("<TEI>"), (
            f"expected TEI input, got {context.script_tei_xml!r}"
        )
        assert action.action_kind is ActionKind.GENERATE_SHOW_NOTES
        if self._event_recorder is not None:
            self._event_recorder.record("execute")
        return self._result


class _PropShowNotesGenerator:
    """Return an empty show-notes result for model-tier boundary probes."""

    async def generate(
        self,
        script_tei_xml: str,
        *,
        template_structure: dict[str, object] | None = None,
    ) -> ShowNotesResult:
        """Return a minimal structured show-notes result."""
        assert script_tei_xml.startswith("<TEI>")
        assert template_structure is not None
        return ShowNotesResult(
            entries=(),
            usage=LLMUsage(input_tokens=1, output_tokens=0, total_tokens=1),
            model="prop-exec-model",
            provider_response_id="prop-exec-response",
            finish_reason="stop",
        )


@dc.dataclass(frozen=True, slots=True)
class _PropTokenInputs:
    """Bundled token-count inputs for LangGraph property tests."""

    planner_input: int
    planner_output: int
    action_input: int
    action_output: int


_token_inputs_strategy: st.SearchStrategy[_PropTokenInputs] = st.builds(
    _PropTokenInputs,
    planner_input=st.integers(min_value=0, max_value=10_000),
    planner_output=st.integers(min_value=0, max_value=10_000),
    action_input=st.integers(min_value=0, max_value=10_000),
    action_output=st.integers(min_value=0, max_value=10_000),
)


@dc.dataclass(frozen=True, slots=True)
class _PropStepKeyInputs:
    """Bundled workflow step identity inputs for idempotency key tests."""

    workflow_id: str
    workflow_type: str
    step_name: str
    action_id: str


_step_key_inputs_strategy: st.SearchStrategy[_PropStepKeyInputs] = st.builds(
    _PropStepKeyInputs,
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

_prop_text = st.text(
    min_size=1,
    max_size=32,
    alphabet=string.ascii_letters + string.digits + "-_ .",
).filter(lambda value: bool(value.strip()))

_usage_strategy = st.builds(
    LLMUsage,
    input_tokens=st.integers(min_value=0, max_value=10_000),
    output_tokens=st.integers(min_value=0, max_value=10_000),
    total_tokens=st.integers(min_value=0, max_value=20_000),
)

_planned_action_strategy = st.builds(
    PlannedAction,
    action_id=_prop_text,
    action_kind=st.just(ActionKind.GENERATE_SHOW_NOTES),
    rationale=_prop_text,
    model_tier=st.just(ModelTier.EXECUTION),
    required_inputs=st.lists(_prop_text, max_size=4).map(tuple),
)

_execution_plan_strategy = st.builds(
    ExecutionPlan,
    plan_version=_prop_text,
    selected_planning_model=_prop_text,
    selected_execution_model=_prop_text,
    steps=st.lists(_planned_action_strategy, min_size=1, max_size=4).map(tuple),
)

_planner_result_strategy = st.builds(
    PlannerResult,
    plan=_execution_plan_strategy,
    usage=st.one_of(st.none(), _usage_strategy),
    model=_prop_text,
    provider_response_id=_prop_text,
    finish_reason=st.one_of(st.none(), _prop_text),
)

_action_result_strategy = st.builds(
    ActionExecutionResult,
    action_id=_prop_text,
    action_kind=st.just(ActionKind.GENERATE_SHOW_NOTES),
    model_tier=st.just(ModelTier.EXECUTION),
    model=_prop_text,
    summary=_prop_text,
    usage=st.one_of(st.none(), _usage_strategy),
)


def _valid_plan_object() -> dict[str, object]:
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


def _invalid_plan_without_plan_version() -> str:
    """Return JSON for a plan object with the required version field omitted."""
    payload = _valid_plan_object()
    payload = {key: value for key, value in payload.items() if key != "plan_version"}
    return json.dumps(payload)


def _invalid_plan_with_top_level_field(field_name: str, value: object) -> str:
    """Return JSON for a plan object with one top-level field replaced."""
    return json.dumps(_valid_plan_object() | {field_name: value})


def _invalid_plan_with_step_field(field_name: str, value: object) -> str:
    """Return JSON for a plan object with one first-step field replaced."""
    step = typ.cast("list[dict[str, object]]", _valid_plan_object()["steps"])[0]
    return json.dumps(_valid_plan_object() | {"steps": [step | {field_name: value}]})


def _invalid_plan_without_step_field(field_name: str) -> str:
    """Return JSON for a plan object with one required first-step field omitted."""
    step = typ.cast("list[dict[str, object]]", _valid_plan_object()["steps"])[0]
    narrowed_step = {key: value for key, value in step.items() if key != field_name}
    return json.dumps(_valid_plan_object() | {"steps": [narrowed_step]})


_unknown_action_kind_values = st.one_of(
    st.none(),
    st.integers(),
    st.text(min_size=1, max_size=512).filter(
        lambda value: value.strip() not in {kind.value for kind in ActionKind}
    ),
)

_unknown_model_tier_values = st.one_of(
    st.none(),
    st.integers(),
    st.text(min_size=1, max_size=512).filter(
        lambda value: value.strip() not in {tier.value for tier in ModelTier}
    ),
)

_invalid_required_inputs_values = st.one_of(
    st.integers(),
    st.lists(st.one_of(st.none(), st.integers(), st.just("")), min_size=1),
)

_invalid_plan_payloads = st.one_of(
    st.just(_invalid_plan_without_plan_version()),
    st.sampled_from(("", " ", "\t")).map(
        lambda value: _invalid_plan_with_top_level_field("plan_version", value)
    ),
    st.one_of(
        st.none(),
        st.integers(),
        st.text(max_size=512),
        st.dictionaries(st.text(min_size=1, max_size=4), st.integers(), max_size=2),
    ).map(lambda value: _invalid_plan_with_top_level_field("steps", value)),
    st.one_of(st.none(), st.integers(), st.text(max_size=512)).map(
        lambda value: _invalid_plan_with_top_level_field("steps", [value])
    ),
    st.just(_invalid_plan_without_step_field("action_id")),
    st.sampled_from(("", " ", "\n")).map(
        lambda value: _invalid_plan_with_step_field("action_id", value)
    ),
    _unknown_action_kind_values.map(
        lambda value: _invalid_plan_with_step_field("action_kind", value)
    ),
    st.sampled_from(("", " ", "\r\n")).map(
        lambda value: _invalid_plan_with_step_field("rationale", value)
    ),
    _unknown_model_tier_values.map(
        lambda value: _invalid_plan_with_step_field("model_tier", value)
    ),
    _invalid_required_inputs_values.map(
        lambda value: _invalid_plan_with_step_field("required_inputs", value)
    ),
)


def test_step_idempotency_key_negative_attempt_raises_value_error() -> None:
    """Negative attempts should be rejected before building a step key."""
    step = WorkflowStepIdentity(
        workflow_id="workflow-id",
        workflow_type="workflow-type",
        step_name="step-name",
        action_id="action-id",
    )

    with pytest.raises(ValueError, match="attempt must be greater than or equal"):
        build_workflow_step_idempotency_key(step, attempt=-1)


@given(
    inputs=_step_key_inputs_strategy,
    attempt=st.integers(min_value=0, max_value=100),
)
@settings(max_examples=50)
def test_step_idempotency_keys_are_deterministic(
    inputs: _PropStepKeyInputs,
    attempt: int,
) -> None:
    """Property test: identical workflow step inputs produce identical keys."""
    step = WorkflowStepIdentity(
        workflow_id=inputs.workflow_id,
        workflow_type=inputs.workflow_type,
        step_name=inputs.step_name,
        action_id=inputs.action_id,
    )
    first = build_workflow_step_idempotency_key(
        step,
        attempt=attempt,
    )
    second = build_workflow_step_idempotency_key(
        step,
        attempt=attempt,
    )
    assert second == first
    assert first.endswith(f":{attempt}")


@given(plan=_execution_plan_strategy)
@settings(max_examples=50)
def test_execution_plan_checkpoint_payload_round_trips(
    plan: ExecutionPlan,
) -> None:
    """Property test: checkpoint plan payloads preserve execution plans."""
    assert _plan_from_payload(_plan_to_payload(plan)) == plan


@given(result=_planner_result_strategy)
@settings(max_examples=50)
def test_planner_result_checkpoint_payload_round_trips(
    result: PlannerResult,
) -> None:
    """Property test: checkpoint planner payloads preserve planner results."""
    assert _planner_result_from_payload(_planner_result_to_payload(result)) == result


@given(result=_action_result_strategy)
@settings(max_examples=50)
def test_action_result_checkpoint_payload_round_trips(
    result: ActionExecutionResult,
) -> None:
    """Property test: checkpoint action payloads preserve action results."""
    assert _action_result_from_payload(_action_result_to_payload(result)) == result


@given(st.lists(st.sampled_from(_ACTION_KIND_SAMPLES), min_size=1, max_size=48))
@settings(max_examples=50)
def test_config_normalises_arbitrary_string_and_enum_mixes(
    kinds: list[ActionKind | str],
) -> None:
    """Property test: heterogeneous action vocabularies become ``ActionKind``."""
    cfg = GenerationOrchestrationConfig(
        planning_model="hyp-plan-model",
        execution_model="hyp-exec-model",
        planning_provider_operation=LLMProviderOperation.CHAT_COMPLETIONS,
        execution_provider_operation=LLMProviderOperation.CHAT_COMPLETIONS,
        enabled_action_kinds=tuple(kinds),
    )
    assert all(isinstance(kind, ActionKind) for kind in cfg.enabled_action_kinds)
    assert cfg.enabled_action_kinds == tuple(ActionKind(str(kind)) for kind in kinds)


@given(
    unknown=st.text(min_size=1, max_size=512).filter(
        lambda s: bool(s.strip()) and s.strip() not in _KNOWN_ACTION_KIND_STRINGS
    )
)
@settings(max_examples=50)
def test_config_rejects_arbitrary_unknown_action_kind_strings(unknown: str) -> None:
    """Property test: unknown action strings invalidate configuration."""
    with pytest.raises(ValueError, match="Unknown action kind"):
        GenerationOrchestrationConfig(
            planning_model="hyp-plan-model",
            execution_model="hyp-exec-model",
            planning_provider_operation=LLMProviderOperation.CHAT_COMPLETIONS,
            execution_provider_operation=LLMProviderOperation.CHAT_COMPLETIONS,
            enabled_action_kinds=(unknown,),
        )


@pytest.mark.parametrize(
    "model_tier",
    [tier for tier in ModelTier if tier is not ModelTier.EXECUTION],
)
@pytest.mark.asyncio
async def test_planned_action_model_tier_rejection_for_all_non_execution_tiers(
    model_tier: ModelTier,
) -> None:
    """Every planner tier besides execution must be rejected by show-notes."""
    fake_llm = _FakeLLMPort([])
    tool_executor = ShowNotesToolExecutor(llm=fake_llm, config=_config())
    planning_tier_action = PlannedAction(
        action_id="action-1",
        action_kind=ActionKind.GENERATE_SHOW_NOTES,
        rationale="Hypothesis rejects non-execution tiers.",
        model_tier=model_tier,
        required_inputs=("script_tei_xml",),
    )
    with pytest.raises(UnsupportedActionError, match=r"requires ModelTier\.EXECUTION"):
        await tool_executor.execute(planning_tier_action, _request())


@pytest.mark.asyncio
async def test_planned_action_execution_model_tier_is_accepted() -> None:
    """Boundary check: execution-tier actions are eligible for show-notes tooling."""
    fake_llm = _FakeLLMPort([])
    tool_executor = ShowNotesToolExecutor(
        llm=fake_llm,
        config=_config(),
        generator=_PropShowNotesGenerator(),
    )
    action = PlannedAction(
        action_id="action-1",
        action_kind=ActionKind.GENERATE_SHOW_NOTES,
        rationale="Hypothesis boundary check for execution tier.",
        model_tier=ModelTier.EXECUTION,
        required_inputs=("script_tei_xml",),
    )

    result = await tool_executor.execute(action, _request())

    assert result.model_tier is ModelTier.EXECUTION
    assert result.summary == "Generated 0 show-notes entries."


@given(
    noise=st.one_of(
        st.integers(),
        st.floats(allow_nan=False, allow_infinity=False),
        st.lists(st.text(max_size=512), max_size=10),
        st.text(max_size=512),
    )
)
@settings(max_examples=50)
@pytest.mark.asyncio
async def test_planning_response_format_error_for_arbitrary_non_object_json(
    noise: object,
) -> None:
    """Property test: non-object JSON bodies fail strict planner validation."""
    blob = json.dumps(noise)

    response = LLMResponse(
        text=blob,
        model="gpt-4.1",
        provider_response_id="hyp-planner-response",
        finish_reason="stop",
        usage=_usage(input_tokens=1, output_tokens=1),
    )
    planner = StructuredGenerationPlanner(
        llm=_FakeLLMPort([response]),
        config=_config(),
    )
    request = GenerationOrchestrationRequest(
        correlation_id="hyp-corr",
        script_tei_xml="<TEI><body><p>noise</p></body></TEI>",
    )
    with pytest.raises(
        PlanningResponseFormatError,
        match=r"planner response must be an object",
    ):
        await planner.plan(request)


@given(payload=_invalid_plan_payloads)
@settings(max_examples=100)
@pytest.mark.asyncio
async def test_planning_response_format_error_for_invalid_plan_objects(
    payload: str,
) -> None:
    """Property test: structurally invalid plan objects preserve format errors."""
    response = LLMResponse(
        text=payload,
        model="gpt-4.1",
        provider_response_id="hyp-invalid-plan-response",
        finish_reason="stop",
        usage=_usage(input_tokens=1, output_tokens=1),
    )
    planner = StructuredGenerationPlanner(
        llm=_FakeLLMPort([response]),
        config=_config(),
    )

    with pytest.raises(PlanningResponseFormatError):
        await planner.plan(_request())


@given(
    tokens=_token_inputs_strategy,
    correlation_id=st.text(
        min_size=1,
        max_size=48,
        alphabet=string.ascii_letters + string.digits + "-",
    ),
)
@settings(max_examples=50)
@pytest.mark.asyncio
async def test_langgraph_total_tokens_non_negative(
    tokens: _PropTokenInputs,
    correlation_id: str,
) -> None:
    """Property test: LangGraph rollups keep total token counts semiring-safe."""
    planner_usage = LLMUsage(
        tokens.planner_input,
        tokens.planner_output,
        tokens.planner_input + tokens.planner_output,
    )
    tool_usage = LLMUsage(
        tokens.action_input,
        tokens.action_output,
        tokens.action_input + tokens.action_output,
    )
    planner_result = PlannerResult(
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
    tool_result = ActionExecutionResult(
        action_id="action-1",
        action_kind=ActionKind.GENERATE_SHOW_NOTES,
        model_tier=ModelTier.EXECUTION,
        model="prop-exec-model",
        summary="prop graph synthesis",
        usage=tool_usage,
    )

    graph = build_generation_orchestration_graph(
        planner=_PropGraphPlanner(result=planner_result),
        tool_executor=_PropGraphToolExecutor(result=tool_result),
    )

    request = GenerationOrchestrationRequest(
        correlation_id=correlation_id,
        script_tei_xml=(
            "<TEI><text><body><p>Hypothesis-driven graph workload</p></body>"
            "</text></TEI>"
        ),
        template_structure=None,
    )
    state = await graph.ainvoke(GenerationGraphState(request=request))
    orchestration_result = state["orchestration_result"]
    expected_total_tokens = planner_usage.total_tokens + tool_usage.total_tokens
    assert orchestration_result.total_usage.input_tokens >= 0
    assert orchestration_result.total_usage.output_tokens >= 0
    assert orchestration_result.total_usage.total_tokens >= 0
    assert orchestration_result.total_usage.total_tokens == expected_total_tokens
    assert state["planner_result"] == planner_result
    assert state["action_results"][0].model == "prop-exec-model"


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
    event_recorder = _GraphEventRecorder()
    planner = _PropGraphPlanner(
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
    tool_executor = _PropGraphToolExecutor(
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
    )

    state = await graph.ainvoke(GenerationGraphState(request=request))
    event_recorder.record("finish")

    assert event_recorder.events == ["plan", "execute", "finish"]
    assert state["planner_result"] is not None
    assert state["action_results"]
    assert state["orchestration_result"] is not None
