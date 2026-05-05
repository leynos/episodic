"""ShowNotesToolExecutor: tool adapter for the show-notes enrichment path."""

import dataclasses as dc
import typing  # noqa: ICN001

from episodic.generation import (
    ShowNotesGenerator,
    ShowNotesGeneratorConfig,
    ShowNotesResult,
)
from episodic.generation.show_notes import ShowNotesResponseFormatError
from episodic.llm import (
    LLMError,
    LLMPort,
    LLMProviderResponseError,
    LLMTransientProviderError,
)

from ._dto import (
    ActionExecutionResult,
    GenerationOrchestrationConfig,
    GenerationOrchestrationRequest,
    PlannedAction,
    _ShowNotesGeneratorPort,
)
from ._types import (
    ActionKind,
    ModelTier,
    ShowNotesFormatError,
    ToolExecutionError,
    UnsupportedActionError,
    _log_event,
)

__all__ = ["ShowNotesToolExecutor"]


_EVENT_PREFIX = "show_notes_tool_executor.execute"
_LLM_PROVIDER_ERROR_EVENTS: dict[type[Exception], str] = {
    LLMTransientProviderError: f"{_EVENT_PREFIX}.transient_provider_error",
    LLMProviderResponseError: f"{_EVENT_PREFIX}.provider_response_error",
    LLMError: f"{_EVENT_PREFIX}.llm_error",
}


def _log_provider_error(
    exc: LLMError,
    context: GenerationOrchestrationRequest,
    action: PlannedAction,
) -> None:
    """Log an LLM provider error with its event name, type, and message."""
    event = _LLM_PROVIDER_ERROR_EVENTS.get(
        type(exc),
        f"{_EVENT_PREFIX}.llm_error",
    )
    _log_event(
        "error",
        event,
        correlation_id=context.correlation_id,
        action_id=action.action_id,
        error_type=type(exc).__name__,
        error=str(exc),
    )


def _handle_generator_error(
    exc: BaseException,
    context: GenerationOrchestrationRequest,
    action: PlannedAction,
) -> typing.Never:
    """Dispatch a generator exception to the appropriate tool-layer error and raise it."""  # noqa: E501
    if isinstance(exc, ToolExecutionError):
        _log_event(
            "error",
            f"{_EVENT_PREFIX}.tool_error",
            correlation_id=context.correlation_id,
            action_id=action.action_id,
        )
        raise exc
    if isinstance(exc, ShowNotesResponseFormatError):
        _log_event(
            "error",
            f"{_EVENT_PREFIX}.format_error",
            correlation_id=context.correlation_id,
            action_id=action.action_id,
        )
        msg = "show-notes tool returned malformed structured JSON"
        raise ShowNotesFormatError(msg) from exc
    if isinstance(exc, LLMError):
        _log_provider_error(exc, context, action)
        raise exc
    _log_event(
        "error",
        f"{_EVENT_PREFIX}.unexpected_error",
        correlation_id=context.correlation_id,
        action_id=action.action_id,
        error_type=type(exc).__name__,
    )
    msg = "show-notes tool execution failed"
    raise ToolExecutionError(msg) from exc


@dc.dataclass(slots=True, frozen=True)
class ShowNotesToolExecutor:
    """Adapter that runs ``generate_show_notes`` through the show-notes generator.

    Validates planned actions, calls the generator with request context, and
    wraps success as an ``ActionExecutionResult``.

    Parameters
    ----------
    llm : LLMPort
        Provider port wired into a lazily instantiated ``ShowNotesGenerator``
        unless ``generator`` is supplied explicitly.
    config : GenerationOrchestrationConfig
        Configuration supplying execution model, provider operation, token budget,
        and system prompt used when constructing the default generator at init.
    generator : _ShowNotesGeneratorPort or None, optional
        Pre-built generator to reuse without construction. When ``None``,
        ``__post_init__`` attaches a freshly built ``ShowNotesGenerator`` backed by
        ``llm`` and ``config`` so callers never observe deferred field mutation
        afterward.
    """

    llm: LLMPort
    config: GenerationOrchestrationConfig
    generator: _ShowNotesGeneratorPort | None = None

    def __post_init__(self) -> None:
        """Build and pin the default show-notes generator when none is injected."""
        if self.generator is None:
            object.__setattr__(
                self,
                "generator",
                ShowNotesGenerator(
                    llm=self.llm,
                    config=ShowNotesGeneratorConfig(
                        model=self.config.execution_model,
                        provider_operation=self.config.execution_provider_operation,
                        token_budget=self.config.execution_token_budget,
                        system_prompt=self.config.execution_system_prompt,
                    ),
                ),
            )

    def _build_generator(self) -> _ShowNotesGeneratorPort:
        """Return the show-notes generator for this executor."""
        gen = self.generator
        if gen is None:
            msg = "ShowNotesToolExecutor.generator was not populated by __post_init__"
            raise RuntimeError(msg)
        return gen

    @staticmethod
    def _validate_action_preconditions(
        action: PlannedAction,
        *,
        correlation_id: str,
    ) -> None:
        """Reject ineligible planned actions by raising ``UnsupportedActionError``."""
        action_kind = str(action.action_kind)
        if action_kind != ActionKind.GENERATE_SHOW_NOTES.value:
            _log_event(
                "error",
                "show_notes_tool_executor.validate.unsupported_action_kind",
                correlation_id=correlation_id,
                action_id=action.action_id,
                action_kind=action_kind,
                expected_action_kind=ActionKind.GENERATE_SHOW_NOTES.value,
            )
            msg = f"Unsupported action kind for show-notes tool: {action.action_kind}"
            raise UnsupportedActionError(msg)
        try:
            normalized_tier = (
                action.model_tier
                if isinstance(action.model_tier, ModelTier)
                else ModelTier(str(action.model_tier).strip())
            )
        except ValueError:
            _log_event(
                "warning",
                "show_notes_tool_executor.validate.invalid_model_tier",
                correlation_id=correlation_id,
                action_id=action.action_id,
                model_tier=str(action.model_tier),
                valid_model_tiers=tuple(tier.value for tier in ModelTier),
            )
            normalized_tier = str(action.model_tier).strip()
        if normalized_tier != ModelTier.EXECUTION:
            _log_event(
                "error",
                "show_notes_tool_executor.validate.unsupported_model_tier",
                correlation_id=correlation_id,
                action_id=action.action_id,
                model_tier=normalized_tier,
                required_model_tier=ModelTier.EXECUTION,
            )
            msg = (
                f"ShowNotesToolExecutor requires ModelTier.EXECUTION; "
                f"got {normalized_tier!r}"
            )
            raise UnsupportedActionError(msg)

    @staticmethod
    async def _invoke_show_notes_generator(
        generator: _ShowNotesGeneratorPort,
        context: GenerationOrchestrationRequest,
        action: PlannedAction,
    ) -> ShowNotesResult:
        """Return ``ShowNotesResult`` from ``generator.generate``; route errors via ``_handle_generator_error``."""  # noqa: E501
        try:
            return await generator.generate(
                context.script_tei_xml,
                template_structure=context.template_structure,
            )
        except Exception as exc:  # noqa: BLE001
            _handle_generator_error(exc, context, action)

    async def execute(
        self,
        action: PlannedAction,
        context: GenerationOrchestrationRequest,
    ) -> ActionExecutionResult:
        """Execute the ``generate_show_notes`` tool step for ``action``.

        Parameters
        ----------
        action : PlannedAction
            Planned step constrained to this executor's supported shape.
        context : GenerationOrchestrationRequest
            Correlation-bound script payload and optional template structure.

        Returns
        -------
        ActionExecutionResult
            Normalised tool outcome wrapping model output and summaries.

        Raises
        ------
        UnsupportedActionError
            When the planner step targets another ``ActionKind`` or model tier.
        ToolExecutionError
            When downstream tool-layer execution fails after logging.
            Includes ``ShowNotesFormatError`` for malformed structured output.
        LLMError
            Forwarded unchanged from generator or provider faults after logging.
        """
        action_kind = str(action.action_kind)
        _log_event(
            "debug",
            "show_notes_tool_executor.execute.start",
            correlation_id=context.correlation_id,
            action_id=action.action_id,
            action_kind=action_kind,
        )
        self._validate_action_preconditions(
            action,
            correlation_id=context.correlation_id,
        )

        generator = self._build_generator()
        result = await self._invoke_show_notes_generator(generator, context, action)

        entry_count = len(result.entries)
        _log_event(
            "info",
            "show_notes_tool_executor.execute.success",
            correlation_id=context.correlation_id,
            action_id=action.action_id,
            entry_count=entry_count,
        )
        noun = "entry" if entry_count == 1 else "entries"
        return ActionExecutionResult(
            action_id=action.action_id,
            action_kind=ActionKind.GENERATE_SHOW_NOTES,
            model_tier=ModelTier.EXECUTION,
            model=result.model,
            summary=f"Generated {entry_count} show-notes {noun}.",
            usage=result.usage,
            show_notes_result=result,
        )
