"""Typed DTOs, protocols, and validation helpers for generation orchestration."""

import dataclasses as dc
import typing as typ

from episodic.llm import (
    LLMProviderOperation,
    LLMTokenBudget,
    LLMUsage,
)

if typ.TYPE_CHECKING:
    from episodic.generation import ShowNotesResult

from ._types import (
    ActionKind,
    ModelTier,
    PlanningResponseFormatError,
)


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


def _coerce_provider_operation(
    value: LLMProviderOperation | str,
    field_name: str,
) -> LLMProviderOperation:
    """Return the provider-operation enum or raise ValueError for unknown values."""
    if isinstance(value, LLMProviderOperation):
        return value
    normalised = _normalize_non_empty_text(value, field_name)
    try:
        return LLMProviderOperation(normalised)
    except ValueError:
        msg = f"Unknown {field_name}: {value!r}"
        raise ValueError(msg) from None


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
        raise ValueError(msg)  # noqa: TRY004 -- ValueError is intentional at this DTO validation raise: normalisation enforces string-shaped fields; TypeError is used for wrong Python types elsewhere.
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
        object.__setattr__(
            self,
            "planning_provider_operation",
            _coerce_provider_operation(
                self.planning_provider_operation,
                "planning_provider_operation",
            ),
        )
        object.__setattr__(
            self,
            "execution_provider_operation",
            _coerce_provider_operation(
                self.execution_provider_operation,
                "execution_provider_operation",
            ),
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
