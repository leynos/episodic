"""Error-path tests for GuestBiosToolExecutor."""

import typing as typ
from uuid import uuid4

import pytest

import episodic.orchestration._guest_bios_executor as guest_bios_executor_module
from episodic.generation import GuestBiosResponseFormatError
from episodic.llm import LLMProviderResponseError, LLMTransientProviderError
from episodic.orchestration import (
    ActionKind,
    GenerationOrchestrationRequest,
    GuestBiosFormatError,
    GuestBiosToolExecutor,
    ModelTier,
    PlannedAction,
    ToolExecutionError,
    UnsupportedActionError,
)
from tests._guest_bios_executor_helpers import (
    SCRIPT_TEI,
    _CustomLLMError,
    _guest_bios_action,
    _RaisingGuestBiosGenerator,
    _single_guest_binding_resolver,
)
from tests._orchestration_fakes import _config, _FakeLLMPort

if typ.TYPE_CHECKING:
    from episodic.canonical.ports import CanonicalUnitOfWork
    from episodic.generation import GuestBiosGenerator
    from episodic.llm import LLMPort


@pytest.mark.asyncio
async def test_guest_bios_tool_executor_requires_series_profile_id() -> None:
    """Binding-backed guest-bios execution needs a series profile context."""
    executor = GuestBiosToolExecutor(
        llm=_FakeLLMPort([]),
        config=_config(),
        uow=typ.cast("CanonicalUnitOfWork", object()),
    )
    request = GenerationOrchestrationRequest(
        correlation_id="corr-guest-bios",
        script_tei_xml=SCRIPT_TEI,
    )

    with pytest.raises(ToolExecutionError, match="series_profile_id"):
        await executor.execute(_guest_bios_action(), request)


@pytest.mark.asyncio
async def test_guest_bios_executor_wraps_format_error_distinctly() -> None:
    """Structured guest-bios validation errors should keep a distinct wrapper."""
    generator_error = GuestBiosResponseFormatError("guests must be a list.")
    executor = GuestBiosToolExecutor(
        llm=typ.cast("LLMPort", None),
        config=_config(),
        uow=typ.cast("CanonicalUnitOfWork", object()),
        generator=typ.cast(
            "GuestBiosGenerator", _RaisingGuestBiosGenerator(generator_error)
        ),
        binding_resolver=_single_guest_binding_resolver,
    )
    request = GenerationOrchestrationRequest(
        correlation_id="corr-guest-bios",
        script_tei_xml=SCRIPT_TEI,
        series_profile_id=uuid4(),
    )

    with pytest.raises(
        GuestBiosFormatError,
        match="malformed structured JSON",
    ) as exc_info:
        await executor.execute(_guest_bios_action(), request)

    assert exc_info.value.__cause__ is generator_error


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [
        pytest.param(
            LLMTransientProviderError("provider transiently failed"),
            id="transient_provider_error",
        ),
        pytest.param(
            LLMProviderResponseError("provider rejected the response"),
            id="provider_response_error",
        ),
    ],
)
async def test_guest_bios_executor_propagates_llm_provider_errors(
    error: BaseException,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Provider errors should surface unchanged and emit provider log context."""
    events: list[tuple[str, str, dict[str, object]]] = []

    def capture_log_event(level: str, message: str, **fields: object) -> None:
        events.append((level, message, fields))

    monkeypatch.setattr(
        guest_bios_executor_module,
        "_log_event",
        capture_log_event,
    )
    executor = GuestBiosToolExecutor(
        llm=typ.cast("LLMPort", None),
        config=_config(),
        uow=typ.cast("CanonicalUnitOfWork", object()),
        generator=typ.cast("GuestBiosGenerator", _RaisingGuestBiosGenerator(error)),
        binding_resolver=_single_guest_binding_resolver,
    )
    request = GenerationOrchestrationRequest(
        correlation_id="corr-guest-bios",
        script_tei_xml=SCRIPT_TEI,
        series_profile_id=uuid4(),
    )

    with pytest.raises(type(error)) as exc_info:
        await executor.execute(_guest_bios_action(), request)

    assert exc_info.value is error
    assert any(
        message.startswith("guest_bios_tool_executor.execute")
        and fields.get("error_type") == type(error).__name__
        for _, message, fields in events
    )


@pytest.mark.asyncio
async def test_guest_bios_executor_wraps_unexpected_generator_error() -> None:
    """Unexpected generator failures should become ToolExecutionError."""
    executor = GuestBiosToolExecutor(
        llm=typ.cast("LLMPort", None),
        config=_config(),
        uow=typ.cast("CanonicalUnitOfWork", object()),
        generator=typ.cast(
            "GuestBiosGenerator",
            _RaisingGuestBiosGenerator(RuntimeError("boom")),
        ),
        binding_resolver=_single_guest_binding_resolver,
    )
    request = GenerationOrchestrationRequest(
        correlation_id="corr-guest-bios",
        script_tei_xml=SCRIPT_TEI,
        series_profile_id=uuid4(),
    )

    with pytest.raises(ToolExecutionError, match="guest-bios tool execution failed"):
        await executor.execute(_guest_bios_action(), request)


@pytest.mark.asyncio
async def test_guest_bios_executor_logs_unknown_llm_subclass(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unmapped LLM errors should use the generic provider log event."""
    error = _CustomLLMError("custom provider failure")
    events: list[tuple[str, str, dict[str, object]]] = []

    def capture_log_event(level: str, message: str, **fields: object) -> None:
        events.append((level, message, fields))

    executor = GuestBiosToolExecutor(
        llm=typ.cast("LLMPort", None),
        config=_config(),
        uow=typ.cast("CanonicalUnitOfWork", object()),
        generator=typ.cast("GuestBiosGenerator", _RaisingGuestBiosGenerator(error)),
        binding_resolver=_single_guest_binding_resolver,
    )
    request = GenerationOrchestrationRequest(
        correlation_id="corr-guest-bios",
        script_tei_xml=SCRIPT_TEI,
        series_profile_id=uuid4(),
    )

    monkeypatch.setattr(
        guest_bios_executor_module,
        "_log_event",
        capture_log_event,
    )

    with pytest.raises(_CustomLLMError):
        await executor.execute(_guest_bios_action(), request)

    assert any(
        message == "guest_bios_tool_executor.execute.llm_error"
        and fields.get("error_type") == "_CustomLLMError"
        for _, message, fields in events
    )


@pytest.mark.asyncio
async def test_guest_bios_tool_executor_rejects_show_notes_action() -> None:
    """The guest-bios executor should not accept another action kind."""
    executor = GuestBiosToolExecutor(
        llm=_FakeLLMPort([]),
        config=_config(),
        uow=typ.cast("CanonicalUnitOfWork", object()),
    )
    action = PlannedAction(
        action_id="show-notes-1",
        action_kind=ActionKind.GENERATE_SHOW_NOTES,
        rationale="Wrong executor.",
        model_tier=ModelTier.EXECUTION,
    )

    with pytest.raises(UnsupportedActionError, match="guest-bios tool"):
        await executor.execute(
            action,
            GenerationOrchestrationRequest(
                correlation_id="corr",
                script_tei_xml=SCRIPT_TEI,
                series_profile_id=uuid4(),
            ),
        )
