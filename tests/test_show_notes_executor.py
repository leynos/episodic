"""Tests for ShowNotesToolExecutor."""

import json
import typing as typ

import pytest

from episodic.generation import (
    ShowNotesEntry,
    ShowNotesResponseFormatError,
)
from episodic.llm import (
    LLMProviderOperation,
    LLMProviderResponseError,
    LLMTransientProviderError,
)
from episodic.orchestration import (
    ActionKind,
    ModelTier,
    PlannedAction,
    ShowNotesFormatError,
    ShowNotesToolExecutor,
    ToolExecutionError,
    UnsupportedActionError,
)
from tests._orchestration_fakes import (
    _config,
    _FakeLLMPort,
    _InjectedToolExecutionError,
    _LLMErrorShowNotesGenerator,
    _MalformedShowNotesGenerator,
    _planned_action,
    _RaisingShowNotesGenerator,
    _request,
    _response,
    _usage,
)


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
