"""Structured planning and tool execution for content generation."""

import dataclasses as dc
import enum
import json
import typing as typ

from episodic.generation import (
    ShowNotesGenerator,
    ShowNotesGeneratorConfig,
    ShowNotesResult,
)
from episodic.generation.show_notes import ShowNotesResponseFormatError
from episodic.llm import (
    LLMError,
    LLMPort,
    LLMProviderOperation,
    LLMProviderResponseError,
    LLMRequest,
    LLMTokenBudget,
    LLMTransientProviderError,
    LLMUsage,
)
from episodic.logging import getLogger

_log = getLogger(__name__)


def _log_event(level: str, message: str, **fields: object) -> None:
    """Emit one structured log event with a JSON fallback."""
    log_method = getattr(_log, level)
    try:
        log_method(message, **fields)
    except TypeError:
        payload = {"event": message, **fields}
        log_method(json.dumps(payload, sort_keys=True))


class ActionKind(enum.StrEnum):
    """Supported generation-enrichment actions for this orchestration slice."""

    GENERATE_SHOW_NOTES = "generate_show_notes"


class ModelTier(enum.StrEnum):
    """Logical model tiers used by the orchestration planner and executor."""

    PLANNING = "planning"
    EXECUTION = "execution"


class PlanningResponseFormatError(ValueError):
    """Raised when the planner returns malformed structured output."""


class UnsupportedActionError(ValueError):
    """Raised when a tool executor receives an unsupported action."""


class ToolExecutionError(RuntimeError):
    """Raised when a planned action fails during tool execution."""


class ShowNotesFormatError(ToolExecutionError):
    """Raised when the show-notes generator returns malformed structured JSON."""


def _require_object(value: object, field_name: str) -> dict[str, object]:
    """Raise TypeError if value is not a plain dict."""
    if isinstance(value, dict):
        return typ.cast("dict[str, object]", value)
    msg = f"{field_name} must be an object."
    raise PlanningResponseFormatError(msg)


def _require_non_empty_string(value: object, field_name: str) -> str:
    """Raise ValueError if value is not a non-empty string."""
    if not isinstance(value, str) or not value.strip():
        msg = f"{field_name} must be a non-empty string."
        raise PlanningResponseFormatError(msg)
    return value.strip()


def _require_optional_string_list(
    value: object,
    field_name: str,
) -> tuple[str, ...]:
    """Raise ValueError if value is neither None nor a list of strings."""
    if value is None:
        return ()
    if not isinstance(value, list):
        msg = f"{field_name} must be a list of strings."
        raise PlanningResponseFormatError(msg)
    items: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            msg = f"{field_name} must contain only non-empty strings."
            raise PlanningResponseFormatError(msg)
        items.append(item.strip())
    return tuple(items)


def _require_plan_step_list(value: object) -> list[dict[str, object]]:
    """Raise ValueError if value is not a non-empty list."""
    if not isinstance(value, list):
        msg = "steps must be a list."
        raise PlanningResponseFormatError(msg)
    return [_require_object(item, "step") for item in value]


def _coerce_action_kind(value: object) -> ActionKind:
    """Return the ActionKind enum for value, raising ValueError for unknown kinds."""
    if not isinstance(value, str):
        msg = "action_kind must be a non-empty string."
        raise PlanningResponseFormatError(msg)
    try:
        return ActionKind(value.strip())
    except ValueError as exc:
        msg = f"action_kind must be one of: {ActionKind.GENERATE_SHOW_NOTES.value}."
        raise PlanningResponseFormatError(msg) from exc


def _coerce_model_tier(value: object) -> ModelTier:
    """Return the ModelTier enum for value, raising ValueError for unknown tiers."""
    if not isinstance(value, str):
        msg = "model_tier must be a non-empty string."
        raise PlanningResponseFormatError(msg)
    try:
        return ModelTier(value.strip())
    except ValueError as exc:
        msg = (
            "model_tier must be one of: "
            f"{ModelTier.PLANNING.value}, {ModelTier.EXECUTION.value}."
        )
        raise PlanningResponseFormatError(msg) from exc


def _coerce_single_action_kind(element: ActionKind | str) -> ActionKind:
    """Return the ActionKind enum for element, raising ValueError for unknown kinds."""
    if isinstance(element, ActionKind):
        return element
    try:
        return ActionKind(str(element).strip())
    except ValueError:
        msg = f"Unknown action kind: {element!r}"
        raise ValueError(msg) from None


def _coerce_action_kinds(
    kinds: tuple[ActionKind | str, ...],
) -> tuple[ActionKind, ...]:
    """Return normalised ActionKind enums, raising ValueError for unknown kinds."""
    if not kinds:
        msg = "enabled_action_kinds must not be empty."
        raise ValueError(msg)
    return tuple(_coerce_single_action_kind(element) for element in kinds)


def _normalize_string_fields(
    obj: object,
    field_names: tuple[str, ...],
) -> None:
    """Normalize each named string field on a frozen dataclass instance in-place."""
    for field_name in field_names:
        value = getattr(obj, field_name)
        object.__setattr__(
            obj, field_name, _normalize_non_empty_text(value, field_name)
        )


def _normalize_non_empty_text(value: object, field_name: str) -> str:
    """Strip value and raise ValueError if the result is empty."""
    if not isinstance(value, str):
        msg = f"{field_name} must be a non-empty string."
        raise ValueError(msg)  # noqa: TRY004
    stripped = value.strip()
    if not stripped:
        msg = f"{field_name} must be a non-empty string."
        raise ValueError(msg)
    return stripped


@dc.dataclass(frozen=True, slots=True)
class GenerationOrchestrationRequest:
    """Typed input for one structured generation-orchestration run."""

    correlation_id: str
    script_tei_xml: str
    template_structure: dict[str, object] | None = None

    def __post_init__(self) -> None:
        """Validate core request invariants eagerly."""
        object.__setattr__(
            self,
            "correlation_id",
            _normalize_non_empty_text(self.correlation_id, "correlation_id"),
        )
        object.__setattr__(
            self,
            "script_tei_xml",
            _normalize_non_empty_text(self.script_tei_xml, "script_tei_xml"),
        )
        if self.template_structure is not None and not isinstance(
            self.template_structure, dict
        ):
            msg = "template_structure must be a mapping object or None."
            raise TypeError(msg)


@dc.dataclass(frozen=True, slots=True)
class GenerationOrchestrationConfig:
    """Planner and executor configuration for structured orchestration."""

    planning_model: str
    execution_model: str
    planning_provider_operation: LLMProviderOperation | str = (
        LLMProviderOperation.CHAT_COMPLETIONS
    )
    execution_provider_operation: LLMProviderOperation | str = (
        LLMProviderOperation.CHAT_COMPLETIONS
    )
    planning_token_budget: LLMTokenBudget | None = None
    execution_token_budget: LLMTokenBudget | None = None
    enabled_action_kinds: tuple[ActionKind | str, ...] = (
        ActionKind.GENERATE_SHOW_NOTES,
    )
    planner_system_prompt: str = dc.field(
        default=(
            "You are the planning stage of the Episodic content generator. "
            "Return JSON only and choose from the enabled action kinds."
        )
    )
    execution_system_prompt: str = dc.field(
        default=(
            "The assistant acts as a podcast show-notes generator. Given a "
            "TEI P5 podcast script, extract the key topics discussed in the "
            "episode. For each topic, provide a short heading and a "
            "one-to-three sentence summary. Return JSON only with key "
            '"entries".'
        )
    )

    def __post_init__(self) -> None:
        """Reject blank config fields and empty action vocabularies."""
        object.__setattr__(
            self,
            "enabled_action_kinds",
            _coerce_action_kinds(self.enabled_action_kinds),
        )
        _normalize_string_fields(
            self,
            (
                "planning_model",
                "execution_model",
                "planner_system_prompt",
                "execution_system_prompt",
            ),
        )


@dc.dataclass(frozen=True, slots=True)
class PlannedAction:
    """One typed step emitted by the structured planner."""

    action_id: str
    action_kind: ActionKind | str
    rationale: str
    model_tier: ModelTier | str
    required_inputs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        """Reject blank identifiers, rationale text, and unknown enum fields."""
        object.__setattr__(
            self,
            "action_id",
            _normalize_non_empty_text(self.action_id, "action_id"),
        )
        object.__setattr__(
            self,
            "rationale",
            _normalize_non_empty_text(self.rationale, "rationale"),
        )
        try:
            action_kind = (
                self.action_kind
                if isinstance(self.action_kind, ActionKind)
                else ActionKind(str(self.action_kind).strip())
            )
        except ValueError:
            msg = f"Unknown action kind: {self.action_kind!r}"
            raise ValueError(msg) from None
        try:
            model_tier = (
                self.model_tier
                if isinstance(self.model_tier, ModelTier)
                else ModelTier(str(self.model_tier).strip())
            )
        except ValueError:
            msg = f"Unknown model tier: {self.model_tier!r}"
            raise ValueError(msg) from None
        object.__setattr__(self, "action_kind", action_kind)
        object.__setattr__(self, "model_tier", model_tier)


@dc.dataclass(frozen=True, slots=True)
class ExecutionPlan:
    """Structured plan derived from one planner response."""

    plan_version: str
    selected_planning_model: str
    selected_execution_model: str
    steps: tuple[PlannedAction, ...]

    def __post_init__(self) -> None:
        """Validate top-level plan metadata and freeze the step sequence."""
        for field_name in (
            "plan_version",
            "selected_planning_model",
            "selected_execution_model",
        ):
            value = getattr(self, field_name)
            object.__setattr__(
                self, field_name, _normalize_non_empty_text(value, field_name)
            )
        steps = tuple(self.steps)
        for index, step in enumerate(steps):
            if not isinstance(step, PlannedAction):
                msg = (
                    f"steps[{index}] must be a PlannedAction; got {type(step).__name__}"
                )
                raise TypeError(msg)
        object.__setattr__(self, "steps", steps)


@dc.dataclass(frozen=True, slots=True)
class PlannerResult:
    """Planner output plus normalized provider metadata."""

    plan: ExecutionPlan
    usage: LLMUsage
    model: str
    provider_response_id: str
    finish_reason: str | None


@dc.dataclass(frozen=True, slots=True)
class ActionExecutionResult:
    """Typed result for one executed orchestration action."""

    action_id: str
    action_kind: ActionKind
    model_tier: ModelTier
    model: str
    summary: str
    usage: LLMUsage | None = None
    show_notes_result: ShowNotesResult | None = None

    def __post_init__(self) -> None:
        """Reject blank user-facing summary text."""
        for field_name in ("action_id", "model", "summary"):
            value = getattr(self, field_name)
            object.__setattr__(
                self, field_name, _normalize_non_empty_text(value, field_name)
            )


@dc.dataclass(frozen=True, slots=True)
class GenerationOrchestrationResult:
    """Aggregated planner and tool output for one orchestration run."""

    plan: ExecutionPlan
    action_results: tuple[ActionExecutionResult, ...]
    planner_usage: LLMUsage
    total_usage: LLMUsage


class ToolExecutorPort(typ.Protocol):
    """Application-level port for executing planned enrichment actions."""

    async def execute(
        self,
        action: PlannedAction,
        context: GenerationOrchestrationRequest,
    ) -> ActionExecutionResult:
        """Execute one planned action against the available generation context."""


class PlannerPort(typ.Protocol):
    """Application-level port for structured orchestration planning."""

    async def plan(
        self,
        request: GenerationOrchestrationRequest,
    ) -> PlannerResult:
        """Return a typed execution plan for the supplied generation request."""


class _ShowNotesGeneratorPort(typ.Protocol):
    """Abstraction for show-notes generation used by the first tool executor."""

    async def generate(
        self,
        script_tei_xml: str,
        *,
        template_structure: dict[str, object] | None = None,
    ) -> ShowNotesResult:
        """Generate show notes from the supplied TEI context."""


def _sum_usage(*usage_values: LLMUsage | None) -> LLMUsage:
    """Return the total token usage across all provided LLMUsage records."""
    input_tokens = 0
    output_tokens = 0
    total_tokens = 0
    for usage in usage_values:
        if usage is None:
            continue
        input_tokens += usage.input_tokens
        output_tokens += usage.output_tokens
        total_tokens += usage.total_tokens
    return LLMUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
    )


def build_generation_result(
    planner_result: PlannerResult,
    action_results: tuple[ActionExecutionResult, ...],
) -> GenerationOrchestrationResult:
    """Aggregate planner and tool usage into one orchestration result."""
    total_usage = _sum_usage(
        planner_result.usage,
        *(action_result.usage for action_result in action_results),
    )
    return GenerationOrchestrationResult(
        plan=planner_result.plan,
        action_results=action_results,
        planner_usage=planner_result.usage,
        total_usage=total_usage,
    )


@dc.dataclass(slots=True)
class StructuredGenerationPlanner:
    """Generate and validate one strict execution plan via `LLMPort`."""

    llm: LLMPort
    config: GenerationOrchestrationConfig

    @staticmethod
    def _parse_plan(
        payload: dict[str, object],
        *,
        config: GenerationOrchestrationConfig,
    ) -> ExecutionPlan:
        """Parse raw LLM JSON text into a validated ExecutionPlan."""
        plan_version = _require_non_empty_string(
            payload.get("plan_version"),
            "plan_version",
        )
        step_payloads = _require_plan_step_list(payload.get("steps"))
        steps = tuple(
            PlannedAction(
                action_id=_require_non_empty_string(
                    step_payload.get("action_id"),
                    "action_id",
                ),
                action_kind=_coerce_action_kind(step_payload.get("action_kind")),
                rationale=_require_non_empty_string(
                    step_payload.get("rationale"),
                    "rationale",
                ),
                model_tier=_coerce_model_tier(step_payload.get("model_tier")),
                required_inputs=_require_optional_string_list(
                    step_payload.get("required_inputs"),
                    "required_inputs",
                ),
            )
            for step_payload in step_payloads
        )
        return ExecutionPlan(
            plan_version=plan_version,
            selected_planning_model=config.planning_model,
            selected_execution_model=config.execution_model,
            steps=steps,
        )

    def build_prompt(self, request: GenerationOrchestrationRequest) -> str:
        """Build the planner prompt payload."""
        enabled_action_kind_values = [
            action_kind.value
            for action_kind in _coerce_action_kinds(self.config.enabled_action_kinds)
        ]
        prompt_payload: dict[str, object] = {
            "task": (
                "Review the canonical TEI script and decide which enabled "
                "generation-enrichment actions should run."
            ),
            "response_schema": {
                "plan_version": "string",
                "steps": [
                    {
                        "action_id": "string",
                        "action_kind": enabled_action_kind_values,
                        "rationale": "string",
                        "model_tier": [
                            ModelTier.PLANNING.value,
                            ModelTier.EXECUTION.value,
                        ],
                        "required_inputs": ["string"],
                    }
                ],
            },
            "enabled_action_kinds": enabled_action_kind_values,
            "correlation_id": request.correlation_id,
            "script_tei_xml": request.script_tei_xml,
        }
        if request.template_structure is not None:
            prompt_payload["template_structure"] = request.template_structure
        try:
            rendered_payload = json.dumps(
                prompt_payload,
                indent=2,
                ensure_ascii=True,
            )
        except TypeError as exc:
            msg = "template_structure must be JSON-serializable."
            raise ValueError(msg) from exc
        return f"Return JSON only.\n{rendered_payload}"

    async def plan(self, request: GenerationOrchestrationRequest) -> PlannerResult:
        """Call the LLM and parse the strict planner response."""
        _log_event(
            "debug",
            "structured_generation_planner.plan.start",
            correlation_id=request.correlation_id,
            planning_model=self.config.planning_model,
        )
        llm_request = LLMRequest(
            model=self.config.planning_model,
            prompt=self.build_prompt(request),
            system_prompt=self.config.planner_system_prompt,
            provider_operation=self.config.planning_provider_operation,
            token_budget=self.config.planning_token_budget,
        )
        try:
            response = await self.llm.generate(llm_request)
        except LLMError:
            _log_event(
                "error",
                "structured_generation_planner.plan.error",
                correlation_id=request.correlation_id,
                planning_model=self.config.planning_model,
            )
            raise
        try:
            decoded = json.loads(response.text)
        except json.JSONDecodeError as exc:
            msg = "Planner response is not valid JSON."
            _log_event(
                "error",
                "structured_generation_planner.plan.invalid_json",
                correlation_id=request.correlation_id,
                planning_model=self.config.planning_model,
            )
            raise PlanningResponseFormatError(msg) from exc
        try:
            payload = _require_object(decoded, "planner response")
            plan = self._parse_plan(payload, config=self.config)
        except PlanningResponseFormatError:
            _log_event(
                "error",
                "structured_generation_planner.plan.invalid_plan",
                correlation_id=request.correlation_id,
                planning_model=self.config.planning_model,
            )
            raise
        _log_event(
            "info",
            "structured_generation_planner.plan.success",
            correlation_id=request.correlation_id,
            planning_model=self.config.planning_model,
            step_count=len(plan.steps),
        )
        return PlannerResult(
            plan=plan,
            usage=response.usage,
            model=response.model,
            provider_response_id=response.provider_response_id,
            finish_reason=response.finish_reason,
        )


@dc.dataclass(slots=True)
class ShowNotesToolExecutor:
    """Execute the `generate_show_notes` action through the show-notes service."""

    llm: LLMPort
    config: GenerationOrchestrationConfig
    generator: _ShowNotesGeneratorPort | None = None

    def _build_generator(self) -> _ShowNotesGeneratorPort:
        """Instantiate a ShowNotesGenerator configured from this executor's settings."""
        if self.generator is not None:
            return self.generator
        return ShowNotesGenerator(
            llm=self.llm,
            config=ShowNotesGeneratorConfig(
                model=self.config.execution_model,
                provider_operation=self.config.execution_provider_operation,
                token_budget=self.config.execution_token_budget,
                system_prompt=self.config.execution_system_prompt,
            ),
        )

    @staticmethod
    def _validate_action_preconditions(
        action: PlannedAction,
        *,
        correlation_id: str,
    ) -> None:
        """Raise UnsupportedActionError if action is not eligible for this executor."""
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
        """Run the show-notes generator and map exceptions to tool-layer errors."""
        try:
            return await generator.generate(
                context.script_tei_xml,
                template_structure=context.template_structure,
            )
        except ToolExecutionError:
            _log_event(
                "error",
                "show_notes_tool_executor.execute.tool_error",
                correlation_id=context.correlation_id,
                action_id=action.action_id,
            )
            raise
        except ShowNotesResponseFormatError as exc:
            _log_event(
                "error",
                "show_notes_tool_executor.execute.format_error",
                correlation_id=context.correlation_id,
                action_id=action.action_id,
            )
            msg = "show-notes tool returned malformed structured JSON"
            raise ShowNotesFormatError(msg) from exc
        except LLMTransientProviderError as exc:
            _log_event(
                "error",
                "show_notes_tool_executor.execute.transient_provider_error",
                correlation_id=context.correlation_id,
                action_id=action.action_id,
                error_type=type(exc).__name__,
                error=str(exc),
            )
            raise
        except LLMProviderResponseError as exc:
            _log_event(
                "error",
                "show_notes_tool_executor.execute.provider_response_error",
                correlation_id=context.correlation_id,
                action_id=action.action_id,
                error_type=type(exc).__name__,
                error=str(exc),
            )
            raise
        except LLMError as exc:
            _log_event(
                "error",
                "show_notes_tool_executor.execute.llm_error",
                correlation_id=context.correlation_id,
                action_id=action.action_id,
                error_type=type(exc).__name__,
                error=str(exc),
            )
            raise
        except Exception as exc:
            _log_event(
                "error",
                "show_notes_tool_executor.execute.unexpected_error",
                correlation_id=context.correlation_id,
                action_id=action.action_id,
                error_type=type(exc).__name__,
            )
            msg = "show-notes tool execution failed"
            raise ToolExecutionError(msg) from exc

    async def execute(
        self,
        action: PlannedAction,
        context: GenerationOrchestrationRequest,
    ) -> ActionExecutionResult:
        """Run the show-notes service for the supported action kind."""
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


@dc.dataclass(slots=True)
class StructuredPlanningOrchestrator:
    """Plan one orchestration run, then execute each planned action in order."""

    planner: PlannerPort
    tool_executor: ToolExecutorPort

    async def execute_plan(
        self,
        *,
        request: GenerationOrchestrationRequest,
        plan: ExecutionPlan,
    ) -> tuple[ActionExecutionResult, ...]:
        """Execute each plan step sequentially through the tool-execution port."""
        # Planned actions may grow side effects later, so execution stays ordered.
        results: list[ActionExecutionResult] = []
        for action in plan.steps:
            results.append(  # noqa: PERF401
                await self.tool_executor.execute(action, request)
            )
        return tuple(results)

    async def orchestrate(
        self,
        request: GenerationOrchestrationRequest,
    ) -> GenerationOrchestrationResult:
        """Plan and execute one structured generation request."""
        _log_event(
            "info",
            "structured_planning_orchestrator.orchestrate.start",
            correlation_id=request.correlation_id,
        )
        try:
            planner_result = await self.planner.plan(request)
        except Exception as exc:
            _log_event(
                "error",
                "structured_planning_orchestrator.orchestrate.error",
                correlation_id=request.correlation_id,
                stage="plan",
                error_type=type(exc).__name__,
                error=str(exc),
            )
            raise
        try:
            action_results = await self.execute_plan(
                request=request,
                plan=planner_result.plan,
            )
        except Exception as exc:
            _log_event(
                "error",
                "structured_planning_orchestrator.orchestrate.error",
                correlation_id=request.correlation_id,
                stage="execute_plan",
                error_type=type(exc).__name__,
                error=str(exc),
            )
            raise
        result = build_generation_result(planner_result, action_results)
        _log_event(
            "info",
            "structured_planning_orchestrator.orchestrate.complete",
            correlation_id=request.correlation_id,
            input_tokens=result.total_usage.input_tokens,
            output_tokens=result.total_usage.output_tokens,
            total_tokens=result.total_usage.total_tokens,
        )
        return result
