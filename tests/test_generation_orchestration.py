"""Unit tests for structured generation orchestration."""

import asyncio
import json
import string
import typing as typ

import hypothesis.strategies as st
import pytest
from hypothesis import given, settings

from episodic.generation import (
    ShowNotesEntry,
    ShowNotesResponseFormatError,
    ShowNotesResult,
)
from episodic.llm import (
    LLMProviderOperation,
    LLMProviderResponseError,
    LLMRequest,
    LLMResponse,
    LLMTransientProviderError,
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
    ShowNotesFormatError,
    ShowNotesToolExecutor,
    StructuredGenerationPlanner,
    StructuredPlanningOrchestrator,
    ToolExecutionError,
    UnsupportedActionError,
    build_generation_orchestration_graph,
)


class _FakeLLMPort:
    """Capture requests and return canned responses in sequence."""

    def __init__(self, responses: list[LLMResponse]) -> None:
        self._responses = responses
        self.requests: list[LLMRequest] = []

    async def generate(self, request: LLMRequest) -> LLMResponse:
        """Return the next canned response after recording the request."""
        self.requests.append(request)
        if not self._responses:
            msg = f"FakeLLM: no more canned responses for request {request}"
            raise AssertionError(msg)
        return self._responses.pop(0)


class _FakeToolExecutor:
    """Capture actions and return canned tool results."""

    def __init__(
        self,
        result: ActionExecutionResult | None = None,
        error: Exception | None = None,
    ) -> None:
        self.result = result
        self.error = error
        self.calls: list[tuple[PlannedAction, GenerationOrchestrationRequest]] = []

    async def execute(
        self,
        action: PlannedAction,
        context: GenerationOrchestrationRequest,
    ) -> ActionExecutionResult:
        """Record the call and either raise or return the canned result."""
        self.calls.append((action, context))
        if self.error is not None:
            raise self.error
        if self.result is None:
            msg = "result must be configured for fake executor"
            raise AssertionError(msg)
        return self.result


class _RaisingShowNotesGenerator:
    """Raise from generate so tool-executor failure paths stay deterministic."""

    async def generate(
        self,
        script_tei_xml: str,
        *,
        template_structure: dict[str, object] | None = None,
    ) -> ShowNotesResult:
        """Raise a deterministic tool error after validating the context."""
        assert script_tei_xml.startswith("<TEI>"), (
            "expected TEI root in generated script_tei_xml"
        )
        assert template_structure == {"sections": ["intro", "analysis"]}, (
            "template_structure does not match expected sections"
        )
        raise _InjectedToolExecutionError


class _LLMErrorShowNotesGenerator:
    """Raise a configurable LLM error so provider failures surface untransformed."""

    def __init__(self, error: BaseException) -> None:
        self._error = error

    async def generate(
        self,
        script_tei_xml: str,
        *,
        template_structure: dict[str, object] | None = None,
    ) -> ShowNotesResult:
        """Raise the injected LLM error after validating the call context."""
        assert script_tei_xml.startswith("<TEI>"), (
            "expected TEI root in generated script_tei_xml"
        )
        assert template_structure == {"sections": ["intro", "analysis"]}, (
            "template_structure does not match expected sections"
        )
        raise self._error


class _MalformedShowNotesGenerator:
    """Raise a response-format error from generate for propagation tests."""

    async def generate(
        self,
        script_tei_xml: str,
        *,
        template_structure: dict[str, object] | None = None,
    ) -> ShowNotesResult:
        """Raise the structured-response validation sentinel."""
        assert script_tei_xml.startswith("<TEI>"), (
            "expected TEI root in generated script_tei_xml"
        )
        assert template_structure == {"sections": ["intro", "analysis"]}, (
            "template_structure does not match expected sections"
        )
        msg = "entries must be a list."
        raise ShowNotesResponseFormatError(msg)


class _InjectedToolExecutionError(ToolExecutionError):
    """Sentinel tool error used to verify pass-through behaviour."""


def _usage(
    *,
    input_tokens: int,
    output_tokens: int,
) -> LLMUsage:
    return LLMUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=input_tokens + output_tokens,
    )


def _response(text: str, *, model: str, usage: LLMUsage) -> LLMResponse:
    return LLMResponse(
        text=text,
        model=model,
        provider_response_id=f"{model}-response",
        finish_reason="stop",
        usage=usage,
    )


def _request() -> GenerationOrchestrationRequest:
    return GenerationOrchestrationRequest(
        correlation_id="corr-123",
        script_tei_xml="<TEI><text><body><p>Episode script</p></body></text></TEI>",
        template_structure={"sections": ["intro", "analysis"]},
    )


def _config() -> GenerationOrchestrationConfig:
    return GenerationOrchestrationConfig(
        planning_model="gpt-4.1",
        execution_model="gpt-4o-mini",
        planning_provider_operation=LLMProviderOperation.CHAT_COMPLETIONS,
        execution_provider_operation=LLMProviderOperation.CHAT_COMPLETIONS,
    )


def _planned_action(*, action_id: str = "action-1") -> PlannedAction:
    return PlannedAction(
        action_id=action_id,
        action_kind=ActionKind.GENERATE_SHOW_NOTES,
        rationale="Show notes are needed for downstream publication surfaces.",
        model_tier=ModelTier.EXECUTION,
        required_inputs=("script_tei_xml",),
    )


def _plan_payload() -> str:
    return json.dumps({
        "plan_version": "1.0",
        "steps": [
            {
                "action_id": "action-1",
                "action_kind": "generate_show_notes",
                "rationale": "Generate publication-ready show notes.",
                "model_tier": "execution",
                "required_inputs": ["script_tei_xml", "template_structure"],
            }
        ],
    })


def test_config_rejects_empty_enabled_action_kinds() -> None:
    """Configuration should reject an empty action vocabulary."""
    with pytest.raises(ValueError, match="enabled_action_kinds must not be empty"):
        GenerationOrchestrationConfig(
            planning_model="gpt-4.1",
            execution_model="gpt-4o-mini",
            enabled_action_kinds=(),
        )


def test_config_normalises_string_action_kinds() -> None:
    """Configuration should accept string-like ActionKind values."""
    config = GenerationOrchestrationConfig(
        planning_model="gpt-4.1",
        execution_model="gpt-4o-mini",
        enabled_action_kinds=("generate_show_notes",),
    )

    assert config.enabled_action_kinds == (ActionKind.GENERATE_SHOW_NOTES,)


def test_planner_rejects_non_json_serializable_template_structure() -> None:
    """Prompt construction should reject non-JSON template structures clearly."""
    planner = StructuredGenerationPlanner(
        llm=_FakeLLMPort([]),
        config=_config(),
    )
    request = GenerationOrchestrationRequest(
        correlation_id="corr-123",
        script_tei_xml="<TEI />",
        template_structure={"bad": object()},
    )

    with pytest.raises(
        ValueError, match="template_structure must be JSON-serializable"
    ):
        planner.build_prompt(request)


def test_config_rejects_unknown_action_kind() -> None:
    """Configuration should fail before unsupported action kinds flow onward."""
    with pytest.raises(
        ValueError,
        match="Unknown action kind: 'unknown_action'",
    ):
        GenerationOrchestrationConfig(
            planning_model="gpt-4.1",
            execution_model="gpt-4o-mini",
            enabled_action_kinds=("unknown_action",),
        )


def test_config_rejects_non_string_text_fields() -> None:
    """Configuration should reject non-string text fields deterministically."""
    with pytest.raises(ValueError, match="planning_model must be a non-empty string"):
        GenerationOrchestrationConfig(
            planning_model=typ.cast("str", object()),
            execution_model="gpt-4o-mini",
        )


def test_planned_action_normalizes_string_enum_fields() -> None:
    """Planned actions should normalize string enum fields at construction."""
    action = PlannedAction(
        action_id="action-1",
        action_kind="generate_show_notes",
        rationale="Generate notes.",
        model_tier="execution",
    )

    assert action.action_kind == ActionKind.GENERATE_SHOW_NOTES
    assert action.model_tier == ModelTier.EXECUTION


@pytest.mark.parametrize(
    ("field_name", "field_value", "expected_match"),
    [
        ("action_kind", typ.cast("ActionKind", object()), "Unknown action kind"),
        ("model_tier", typ.cast("ModelTier", object()), "Unknown model tier"),
    ],
)
def test_planned_action_rejects_unknown_enum_fields(
    field_name: str,
    field_value: ActionKind | ModelTier,
    expected_match: str,
) -> None:
    """Planned actions should reject invalid enum-like field values."""
    kwargs: dict[str, object] = {
        "action_id": "action-1",
        "action_kind": ActionKind.GENERATE_SHOW_NOTES,
        "rationale": "Generate notes.",
        "model_tier": ModelTier.EXECUTION,
    }
    kwargs[field_name] = field_value

    with pytest.raises(ValueError, match=expected_match):
        PlannedAction(**typ.cast("typ.Any", kwargs))


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


@pytest.mark.asyncio
async def test_orchestrator_dispatches_through_tool_port() -> None:
    """Orchestrator should execute planned actions via the tool port only."""
    llm = _FakeLLMPort([
        _response(
            _plan_payload(),
            model="gpt-4.1",
            usage=_usage(input_tokens=20, output_tokens=10),
        )
    ])
    planner = StructuredGenerationPlanner(llm=llm, config=_config())
    tool_result = ActionExecutionResult(
        action_id="action-1",
        action_kind=ActionKind.GENERATE_SHOW_NOTES,
        model_tier=ModelTier.EXECUTION,
        model="gpt-4o-mini",
        summary="Generated one show-notes payload.",
        usage=_usage(input_tokens=12, output_tokens=8),
    )
    tool_executor = _FakeToolExecutor(result=tool_result)
    orchestrator = StructuredPlanningOrchestrator(
        planner=planner,
        tool_executor=tool_executor,
    )

    result = await orchestrator.orchestrate(_request())

    assert len(tool_executor.calls) == 1
    planned_action, context = tool_executor.calls[0]
    assert planned_action.action_kind is ActionKind.GENERATE_SHOW_NOTES
    assert context.correlation_id == "corr-123"
    assert result.action_results == (tool_result,)
    assert result.total_usage == _usage(input_tokens=32, output_tokens=18)


@pytest.mark.asyncio
async def test_orchestrator_propagates_tool_failures() -> None:
    """Tool errors should not be swallowed by the orchestration layer."""
    llm = _FakeLLMPort([
        _response(
            _plan_payload(),
            model="gpt-4.1",
            usage=_usage(input_tokens=20, output_tokens=10),
        )
    ])
    planner = StructuredGenerationPlanner(llm=llm, config=_config())
    tool_executor = _FakeToolExecutor(error=ToolExecutionError("tool exploded"))
    orchestrator = StructuredPlanningOrchestrator(
        planner=planner,
        tool_executor=tool_executor,
    )

    with pytest.raises(ToolExecutionError, match="tool exploded"):
        await orchestrator.orchestrate(_request())


@pytest.mark.asyncio
async def test_show_notes_tool_executor_uses_execution_model_and_returns_result() -> (
    None
):
    """Show-notes tool execution should honour the configured execution tier."""
    llm = _FakeLLMPort([
        _response(
            json.dumps({
                "entries": [
                    {
                        "topic": "Introduction",
                        "summary": "Opening remarks.",
                        "timestamp": "PT0M30S",
                    }
                ]
            }),
            model="gpt-4o-mini",
            usage=_usage(input_tokens=18, output_tokens=7),
        )
    ])
    tool_executor = ShowNotesToolExecutor(llm=llm, config=_config())

    result = await tool_executor.execute(_planned_action(), _request())

    assert result.model == "gpt-4o-mini"
    assert result.usage == _usage(input_tokens=18, output_tokens=7)
    assert result.show_notes_result is not None
    assert result.show_notes_result.entries[0] == ShowNotesEntry(
        topic="Introduction",
        summary="Opening remarks.",
        timestamp="PT0M30S",
    )

    request = llm.requests[0]
    assert request.model == "gpt-4o-mini"
    assert request.provider_operation == LLMProviderOperation.CHAT_COMPLETIONS


@pytest.mark.asyncio
async def test_show_notes_tool_executor_accepts_execution_tier_string() -> None:
    """Show-notes executor should normalize valid string model tiers."""
    llm = _FakeLLMPort([
        _response(
            json.dumps({
                "entries": [
                    {
                        "topic": "Introduction",
                        "summary": "Opening remarks.",
                    }
                ]
            }),
            model="gpt-4o-mini",
            usage=_usage(input_tokens=18, output_tokens=7),
        )
    ])
    tool_executor = ShowNotesToolExecutor(llm=llm, config=_config())
    action = PlannedAction(
        action_id="action-1",
        action_kind=ActionKind.GENERATE_SHOW_NOTES,
        rationale="Show notes are needed for downstream publication surfaces.",
        model_tier="execution",
        required_inputs=("script_tei_xml",),
    )

    result = await tool_executor.execute(action, _request())

    assert result.model_tier == ModelTier.EXECUTION


def test_show_notes_tool_executor_rejects_unsupported_action_kind() -> None:
    """Unsupported action kinds should fail before tool execution."""
    with pytest.raises(ValueError, match="Unknown action kind: 'generate_guest_bio'"):
        PlannedAction(
            action_id="action-2",
            action_kind=typ.cast("ActionKind", "generate_guest_bio"),
            rationale="Not supported in this slice.",
            model_tier=ModelTier.EXECUTION,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("model_tier", "expected_tier_pattern"),
    [(ModelTier.PLANNING, r"ModelTier\.EXECUTION")],
)
async def test_show_notes_executor_rejects_planning_tier(
    model_tier: ModelTier,
    expected_tier_pattern: str,
) -> None:
    """Show-notes execution should only run on the execution model tier."""
    llm = _FakeLLMPort([])
    tool_executor = ShowNotesToolExecutor(llm=llm, config=_config())
    planning_tier_action = PlannedAction(
        action_id="action-1",
        action_kind=ActionKind.GENERATE_SHOW_NOTES,
        rationale="Show notes are needed for downstream publication surfaces.",
        model_tier=model_tier,
        required_inputs=("script_tei_xml",),
    )

    with pytest.raises(UnsupportedActionError, match=expected_tier_pattern):
        await tool_executor.execute(planning_tier_action, _request())


@pytest.mark.asyncio
async def test_show_notes_tool_executor_wraps_generator_failures() -> None:
    """Show-notes tool should surface deterministic execution failures."""
    tool_executor = ShowNotesToolExecutor(
        llm=typ.cast("typ.Any", None),
        config=_config(),
        generator=typ.cast("typ.Any", _RaisingShowNotesGenerator()),
    )

    with pytest.raises(ToolExecutionError) as exc_info:
        await tool_executor.execute(_planned_action(), _request())

    assert isinstance(exc_info.value, _InjectedToolExecutionError)


@pytest.mark.asyncio
async def test_show_notes_executor_wraps_format_error_distinctly() -> None:
    """Structured show-notes validation errors should keep a distinct wrapper."""
    tool_executor = ShowNotesToolExecutor(
        llm=typ.cast("typ.Any", None),
        config=_config(),
        generator=typ.cast("typ.Any", _MalformedShowNotesGenerator()),
    )

    with pytest.raises(
        ShowNotesFormatError, match="malformed structured JSON"
    ) as exc_info:
        await tool_executor.execute(_planned_action(), _request())

    assert isinstance(exc_info.value.__cause__, ShowNotesResponseFormatError)


@pytest.mark.asyncio
async def test_show_notes_executor_format_error_is_subtype_of_tool_execution_error() -> (  # noqa: E501
    None
):
    """Structured show-notes validation errors should remain distinguishable."""
    tool_executor = ShowNotesToolExecutor(
        llm=typ.cast("typ.Any", None),
        config=_config(),
        generator=typ.cast("typ.Any", _MalformedShowNotesGenerator()),
    )

    with pytest.raises(ToolExecutionError) as exc_info:
        await tool_executor.execute(_planned_action(), _request())

    assert isinstance(exc_info.value, ShowNotesFormatError)
    assert type(exc_info.value) is not ToolExecutionError


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error_factory",
    [
        pytest.param(
            lambda: LLMTransientProviderError("provider transiently failed"),
            id="transient_provider_error",
        ),
        pytest.param(
            lambda: LLMProviderResponseError("provider rejected the response"),
            id="provider_response_error",
        ),
    ],
)
async def test_show_notes_executor_propagates_llm_provider_errors(
    error_factory: typ.Callable[[], BaseException],
) -> None:
    """Provider errors must surface unchanged so callers can classify them."""
    error = error_factory()
    tool_executor = ShowNotesToolExecutor(
        llm=typ.cast("typ.Any", None),
        config=_config(),
        generator=typ.cast("typ.Any", _LLMErrorShowNotesGenerator(error)),
    )

    with pytest.raises(type(error)) as exc_info:
        await tool_executor.execute(_planned_action(), _request())

    assert exc_info.value is error
    assert not isinstance(exc_info.value, ToolExecutionError)


_ACTION_KIND_SAMPLES: tuple[ActionKind | str, ...] = tuple(ActionKind) + tuple(
    m.value for m in ActionKind
)
_KNOWN_ACTION_KIND_STRINGS = {m.value for m in ActionKind}


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
@settings(max_examples=50)
def test_planned_action_model_tier_rejection_for_all_non_execution_tiers(
    model_tier: ModelTier,
) -> None:
    """Property test: planner tiers besides execution never reach show-notes tool."""

    async def runner() -> None:
        fake_llm = _FakeLLMPort([])
        tool_executor = ShowNotesToolExecutor(llm=fake_llm, config=_config())
        planning_tier_action = PlannedAction(
            action_id="action-1",
            action_kind=ActionKind.GENERATE_SHOW_NOTES,
            rationale="Hypothesis rejects non-execution tiers.",
            model_tier=model_tier,
            required_inputs=("script_tei_xml",),
        )
        with pytest.raises(UnsupportedActionError):
            await tool_executor.execute(planning_tier_action, _request())

    asyncio.run(runner())


@given(
    noise=st.one_of(
        st.integers(),
        st.floats(allow_nan=False, allow_infinity=False),
        st.lists(st.text()),
        st.text(),
    )
)
@settings(max_examples=50)
def test_planning_response_format_error_for_arbitrary_non_object_json(
    noise: object,
) -> None:
    """Property test: non-object JSON bodies fail strict planner validation."""
    blob = json.dumps(noise)

    async def runner() -> None:
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
        with pytest.raises(PlanningResponseFormatError):
            await planner.plan(request)

    asyncio.run(runner())


class _PropGraphPlanner:
    """Emit canned planner payloads for Hypothesis graph probes."""

    def __init__(self, *, result: PlannerResult) -> None:
        self._result = result

    async def plan(self, request: GenerationOrchestrationRequest) -> PlannerResult:
        assert request.script_tei_xml.startswith("<TEI>")
        assert request.correlation_id
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
        assert context.script_tei_xml.startswith("<TEI>")
        assert action.action_kind is ActionKind.GENERATE_SHOW_NOTES
        return self._result


@given(
    planner_input=st.integers(min_value=0, max_value=10_000),
    planner_output=st.integers(min_value=0, max_value=10_000),
    action_input=st.integers(min_value=0, max_value=10_000),
    action_output=st.integers(min_value=0, max_value=10_000),
    correlation_id=st.text(
        min_size=1,
        max_size=48,
        alphabet=string.ascii_letters + string.digits + "-",
    ),
)
@settings(max_examples=50)
def test_langgraph_total_tokens_non_negative(
    planner_input: int,
    planner_output: int,
    action_input: int,
    action_output: int,
    correlation_id: str,
) -> None:
    """Property test: LangGraph rollups keep total token counts semiring-safe."""
    planner_usage = LLMUsage(
        planner_input,
        planner_output,
        planner_input + planner_output,
    )
    tool_usage = LLMUsage(action_input, action_output, action_input + action_output)
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

    async def runner() -> None:
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

    asyncio.run(runner())
