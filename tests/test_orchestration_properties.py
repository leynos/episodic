"""Hypothesis property-based tests for orchestration invariants."""

import dataclasses as dc
import json
import string

import hypothesis.strategies as st
import pytest
from hypothesis import given, settings

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
    build_generation_orchestration_graph,
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


class _PropGraphPlanner:
    """Emit canned planner payloads for Hypothesis graph probes."""

    def __init__(self, *, result: PlannerResult) -> None:
        self._result = result

    async def plan(self, request: GenerationOrchestrationRequest) -> PlannerResult:
        assert request.script_tei_xml.startswith("<TEI>"), (
            f"expected TEI input, got {request.script_tei_xml!r}"
        )
        assert request.correlation_id, "expected non-empty correlation_id"
        return self._result


class _PropGraphToolExecutor:
    """Emit canned tool payloads for Hypothesis graph probes."""

    def __init__(self, result: ActionExecutionResult) -> None:
        self._result = result

    async def execute(
        self,
        action: PlannedAction,
        context: GenerationOrchestrationRequest,
    ) -> ActionExecutionResult:
        assert context.script_tei_xml.startswith("<TEI>"), (
            f"expected TEI input, got {context.script_tei_xml!r}"
        )
        assert action.action_kind is ActionKind.GENERATE_SHOW_NOTES
        return self._result


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


@given(
    unknown=st.text(min_size=1).filter(
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


@given(model_tier=st.sampled_from([t for t in ModelTier if t != ModelTier.EXECUTION]))
@settings(max_examples=len(ModelTier))
@pytest.mark.asyncio
async def test_planned_action_model_tier_rejection_for_all_non_execution_tiers(
    model_tier: ModelTier,
) -> None:
    """Property test: planner tiers besides execution never reach show-notes tool."""
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


@given(
    noise=st.one_of(
        st.integers(),
        st.floats(allow_nan=False, allow_infinity=False),
        st.lists(st.text()),
        st.text(),
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
    assert orchestration_result.total_usage.total_tokens >= 0
    assert orchestration_result.total_usage.total_tokens == expected_total_tokens
    assert state["planner_result"] == planner_result
    assert state["action_results"][0].model == "prop-exec-model"
