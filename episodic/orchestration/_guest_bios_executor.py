"""GuestBiosToolExecutor: tool adapter for guest-bio enrichment."""

import collections.abc as cabc  # noqa: TC003 - BindingResolver protocol is part of the runtime executor contract.
import dataclasses as dc
import typing  # noqa: ICN001

from episodic.generation import (
    GuestBiosEnrichmentRequest,
    GuestBiosGenerator,
    GuestBiosGeneratorConfig,
    generate_guest_bios_from_reference_bindings,
)
from episodic.generation.guest_bios import GuestBiosResponseFormatError
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
)
from ._types import (
    ActionKind,
    GuestBiosFormatError,
    ModelTier,
    ToolExecutionError,
    UnsupportedActionError,
    _log_event,
)

if typing.TYPE_CHECKING:
    import uuid

    from episodic.canonical.ports import CanonicalUnitOfWork
    from episodic.canonical.reference_documents.resolution import ResolvedBinding

__all__ = ["GuestBiosToolExecutor"]


_EVENT_PREFIX = "guest_bios_tool_executor.execute"
_LLM_PROVIDER_ERROR_EVENTS: dict[type[Exception], str] = {
    LLMTransientProviderError: f"{_EVENT_PREFIX}.transient_provider_error",
    LLMProviderResponseError: f"{_EVENT_PREFIX}.provider_response_error",
    LLMError: f"{_EVENT_PREFIX}.llm_error",
}


class BindingResolver(typing.Protocol):  # pylint: disable=too-many-arguments
    """Resolve pinned reference-document bindings for one generation context."""

    def __call__(  # pylint: disable=too-many-arguments
        self,
        uow: CanonicalUnitOfWork,
        *,
        series_profile_id: uuid.UUID,
        template_id: uuid.UUID | None = None,
        episode_id: uuid.UUID | None = None,
    ) -> cabc.Awaitable[list[ResolvedBinding]]:
        """Return resolved bindings for series, template, and episode context."""


def _log_provider_error(
    exc: LLMError,
    context: GenerationOrchestrationRequest,
    action: PlannedAction,
) -> None:
    """Log an LLM provider error with its event name, type, and message."""
    event = f"{_EVENT_PREFIX}.llm_error"
    for error_type in exc.__class__.mro():
        exception_type = typing.cast("type[Exception]", error_type)
        if exception_type in _LLM_PROVIDER_ERROR_EVENTS:
            event = _LLM_PROVIDER_ERROR_EVENTS[exception_type]
            break
    _log_event(
        "error",
        event,
        correlation_id=context.correlation_id,
        action_id=action.action_id,
        error_type=type(exc).__name__,
        error=str(exc),
    )


def _handle_generator_error(
    exc: Exception,
    context: GenerationOrchestrationRequest,
    action: PlannedAction,
) -> typing.Never:
    """Dispatch a generator exception to the appropriate tool-layer error."""
    if isinstance(exc, ToolExecutionError):
        _log_event(
            "error",
            f"{_EVENT_PREFIX}.tool_error",
            correlation_id=context.correlation_id,
            action_id=action.action_id,
        )
        raise exc
    if isinstance(exc, GuestBiosResponseFormatError):
        _log_event(
            "error",
            f"{_EVENT_PREFIX}.format_error",
            correlation_id=context.correlation_id,
            action_id=action.action_id,
        )
        msg = "guest-bios tool returned malformed structured JSON"
        raise GuestBiosFormatError(msg) from exc
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
    msg = "guest-bios tool execution failed"
    raise ToolExecutionError(msg) from exc


@dc.dataclass(slots=True, frozen=True)
class GuestBiosToolExecutor:  # pylint: disable=too-many-arguments
    """Adapter that runs ``generate_guest_bios`` through the guest-bios generator."""

    llm: LLMPort
    config: GenerationOrchestrationConfig
    uow: CanonicalUnitOfWork
    generator: GuestBiosGenerator | None = None
    binding_resolver: BindingResolver | None = None

    def __post_init__(self) -> None:
        """Build and store the guest-bios generator when none is injected."""
        if self.generator is None:
            object.__setattr__(
                self,
                "generator",
                GuestBiosGenerator(
                    llm=self.llm,
                    config=GuestBiosGeneratorConfig(
                        model=self.config.execution_model,
                        provider_operation=self.config.execution_provider_operation,
                        token_budget=self.config.execution_token_budget,
                    ),
                ),
            )

    def _get_generator(self) -> GuestBiosGenerator:
        """Return the pre-built guest-bios generator."""
        assert self.generator is not None  # noqa: S101  # guaranteed by __post_init__
        return self.generator

    @staticmethod
    def _validate_action_preconditions(
        action: PlannedAction,
        *,
        correlation_id: str,
    ) -> None:
        """Reject ineligible planned actions by raising ``UnsupportedActionError``."""
        if action.action_kind != ActionKind.GENERATE_GUEST_BIOS:
            _log_event(
                "error",
                "guest_bios_tool_executor.validate.unsupported_action_kind",
                correlation_id=correlation_id,
                action_id=action.action_id,
                action_kind=str(action.action_kind),
                expected_action_kind=ActionKind.GENERATE_GUEST_BIOS.value,
            )
            msg = f"Unsupported action kind for guest-bios tool: {action.action_kind}"
            raise UnsupportedActionError(msg)
        if action.model_tier != ModelTier.EXECUTION:
            _log_event(
                "error",
                "guest_bios_tool_executor.validate.unsupported_model_tier",
                correlation_id=correlation_id,
                action_id=action.action_id,
                model_tier=str(action.model_tier),
                required_model_tier=ModelTier.EXECUTION.value,
            )
            msg = (
                f"GuestBiosToolExecutor requires ModelTier.EXECUTION; "
                f"got {action.model_tier!r}"
            )
            raise UnsupportedActionError(msg)

    @staticmethod
    def _require_series_profile_id(
        context: GenerationOrchestrationRequest,
    ) -> uuid.UUID:
        """Return the series profile identifier required for binding resolution."""
        if context.series_profile_id is None:
            msg = "generate_guest_bios requires series_profile_id on the request."
            raise ToolExecutionError(msg)
        return context.series_profile_id

    async def execute(
        self,
        action: PlannedAction,
        context: GenerationOrchestrationRequest,
    ) -> ActionExecutionResult:
        """Execute the ``generate_guest_bios`` tool step for ``action``."""
        action_kind = str(action.action_kind)
        _log_event(
            "debug",
            "guest_bios_tool_executor.execute.start",
            correlation_id=context.correlation_id,
            action_id=action.action_id,
            action_kind=action_kind,
        )
        self._validate_action_preconditions(
            action,
            correlation_id=context.correlation_id,
        )

        try:
            series_profile_id = self._require_series_profile_id(context)
            generation_kwargs = {}
            if self.binding_resolver is not None:
                generation_kwargs["binding_resolver"] = self.binding_resolver
            result = await generate_guest_bios_from_reference_bindings(
                self.uow,
                GuestBiosEnrichmentRequest(
                    series_profile_id=series_profile_id,
                    tei_xml=context.script_tei_xml,
                    template_id=context.template_id,
                    episode_id=context.episode_id,
                    template_structure=context.template_structure,
                ),
                generator=self._get_generator(),
                **generation_kwargs,
            )
        except Exception as exc:  # noqa: BLE001
            _handle_generator_error(exc, context, action)

        entry_count = len(result.generation_result.entries)
        _log_event(
            "info",
            "guest_bios_tool_executor.execute.success",
            correlation_id=context.correlation_id,
            action_id=action.action_id,
            entry_count=entry_count,
        )
        noun = "biography" if entry_count == 1 else "biographies"
        return ActionExecutionResult(
            action_id=action.action_id,
            action_kind=ActionKind.GENERATE_GUEST_BIOS,
            model_tier=ModelTier.EXECUTION,
            model=result.generation_result.model,
            summary=f"Generated {entry_count} guest {noun}.",
            usage=result.generation_result.usage,
            guest_bios_result=result,
        )
