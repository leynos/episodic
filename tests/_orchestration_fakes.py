"""Shared fakes and builder helpers for orchestration tests."""

import json
import typing as typ

from episodic.generation import (
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
    ToolExecutionError,
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


def _assert_generate_context(
    script_tei_xml: str,
    template_structure: dict[str, object] | None,
) -> None:
    """Assert that the generator received the expected invocation context."""
    assert script_tei_xml.startswith("<TEI>"), (  # noqa: S101
        "expected TEI root in generated script_tei_xml"
    )
    assert template_structure == {"sections": ["intro", "analysis"]}, (  # noqa: S101
        "template_structure does not match expected sections"
    )


class _BaseShowNotesGenerator:
    """Interface for fakes that emulate show-notes generation."""

    async def generate(
        self,
        script_tei_xml: str,
        *,
        template_structure: dict[str, object] | None = None,
    ) -> ShowNotesResult:
        """Generate show notes for a fake test context."""
        raise NotImplementedError


class _RaisingShowNotesGenerator(_BaseShowNotesGenerator):
    """Raise from generate so tool-executor failure paths stay deterministic."""

    @typ.override
    async def generate(
        self,
        script_tei_xml: str,
        *,
        template_structure: dict[str, object] | None = None,
    ) -> ShowNotesResult:
        """Raise a deterministic tool error after validating the context."""
        _assert_generate_context(script_tei_xml, template_structure)
        raise _InjectedToolExecutionError


class _LLMErrorShowNotesGenerator(_BaseShowNotesGenerator):
    """Raise a configurable LLM error so provider failures surface untransformed."""

    def __init__(self, error: BaseException) -> None:
        self._error = error

    @typ.override
    async def generate(
        self,
        script_tei_xml: str,
        *,
        template_structure: dict[str, object] | None = None,
    ) -> ShowNotesResult:
        """Raise the injected LLM error after validating the call context."""
        _assert_generate_context(script_tei_xml, template_structure)
        raise self._error


class _MalformedShowNotesGenerator(_BaseShowNotesGenerator):
    """Raise a response-format error from generate for propagation tests."""

    @typ.override
    async def generate(
        self,
        script_tei_xml: str,
        *,
        template_structure: dict[str, object] | None = None,
    ) -> ShowNotesResult:
        """Raise the structured-response validation sentinel."""
        _assert_generate_context(script_tei_xml, template_structure)
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
