"""Unit tests for structured generation orchestration."""

from __future__ import annotations

import asyncio
import json
import typing as typ

import pytest

from episodic.generation import (
    ShowNotesEntry,
    ShowNotesResponseFormatError,
    ShowNotesResult,
)
from episodic.llm import (
    LLMProviderOperation,
    LLMRequest,
    LLMResponse,
    LLMUsage,
)
from episodic.orchestration import (
    ActionExecutionResult,
    ActionKind,
    GenerationOrchestrationConfig,
    GenerationOrchestrationRequest,
    ModelTier,
    PlannedAction,
    PlanningResponseFormatError,
    ShowNotesFormatError,
    ShowNotesToolExecutor,
    StructuredGenerationPlanner,
    StructuredPlanningOrchestrator,
    ToolExecutionError,
    UnsupportedActionError,
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


@pytest.mark.asyncio
async def test_config_rejects_empty_enabled_action_kinds() -> None:
    """Configuration should reject an empty action vocabulary."""
    await asyncio.sleep(0)

    with pytest.raises(ValueError, match="enabled_action_kinds must not be empty"):
        GenerationOrchestrationConfig(
            planning_model="gpt-4.1",
            execution_model="gpt-4o-mini",
            enabled_action_kinds=(),
        )


@pytest.mark.asyncio
async def test_config_normalises_string_action_kinds() -> None:
    """Configuration should accept string-like ActionKind values."""
    await asyncio.sleep(0)

    config = GenerationOrchestrationConfig(
        planning_model="gpt-4.1",
        execution_model="gpt-4o-mini",
        enabled_action_kinds=typ.cast(
            "tuple[ActionKind, ...]",
            (" generate_show_notes ",),
        ),
    )

    assert config.enabled_action_kinds == (ActionKind.GENERATE_SHOW_NOTES,)


@pytest.mark.asyncio
async def test_planner_rejects_non_json_serializable_template_structure() -> None:
    """Prompt construction should reject non-JSON template structures clearly."""
    await asyncio.sleep(0)
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


@pytest.mark.asyncio
async def test_config_rejects_unknown_action_kind() -> None:
    """Configuration should fail before unsupported action kinds flow onward."""
    await asyncio.sleep(0)

    with pytest.raises(
        ValueError,
        match="Unknown action kind: 'unknown_action'",
    ):
        GenerationOrchestrationConfig(
            planning_model="gpt-4.1",
            execution_model="gpt-4o-mini",
            enabled_action_kinds=typ.cast(
                "tuple[ActionKind, ...]",
                ("unknown_action",),
            ),
        )


@pytest.mark.asyncio
async def test_config_rejects_non_string_text_fields() -> None:
    """Configuration should reject non-string text fields deterministically."""
    await asyncio.sleep(0)

    with pytest.raises(ValueError, match="planning_model must be a non-empty string"):
        GenerationOrchestrationConfig(
            planning_model=typ.cast("str", object()),
            execution_model="gpt-4o-mini",
        )


@pytest.mark.asyncio
async def test_planned_action_normalizes_string_enum_fields() -> None:
    """Planned actions should normalize string enum fields at construction."""
    await asyncio.sleep(0)

    action = PlannedAction(
        action_id="action-1",
        action_kind="generate_show_notes",
        rationale="Generate notes.",
        model_tier="execution",
    )

    assert action.action_kind == ActionKind.GENERATE_SHOW_NOTES
    assert action.model_tier == ModelTier.EXECUTION


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field_name", "field_value", "expected_match"),
    [
        ("action_kind", typ.cast("ActionKind", object()), "Unknown action kind"),
        ("model_tier", typ.cast("ModelTier", object()), "Unknown model tier"),
    ],
)
async def test_planned_action_rejects_unknown_enum_fields(
    field_name: str,
    field_value: ActionKind | ModelTier,
    expected_match: str,
) -> None:
    """Planned actions should reject invalid enum-like field values."""
    await asyncio.sleep(0)
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


@pytest.mark.asyncio
async def test_show_notes_tool_executor_rejects_unsupported_action_kind() -> None:
    """Unsupported action kinds should fail before tool execution."""
    await asyncio.sleep(0)

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
