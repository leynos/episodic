"""Provider-neutral DTOs for orchestration payload boundaries."""

import collections.abc as cabc
import dataclasses as dc
import typing as typ

from episodic.llm import (
    LLMProviderOperation,
    LLMUsage,
    ProviderCallUsage,
)

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
        expected = ", ".join(action.value for action in ActionKind)
        msg = f"action_kind must be one of: {expected}."
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


def _coerce_single_model_tier(element: ModelTier | str) -> ModelTier:
    """Return the ModelTier enum for element, raising ValueError for unknown tiers."""
    if isinstance(element, ModelTier):
        return element
    try:
        return ModelTier(str(element).strip())
    except ValueError:
        msg = f"Unknown model tier: {element!r}"
        raise ValueError(msg) from None


def _raise_required_inputs_value_error() -> typ.Never:
    """Raise ValueError for malformed required_inputs values."""
    msg = "required_inputs must be an iterable of non-empty strings."
    raise ValueError(msg)


def _normalize_required_inputs(value: object) -> tuple[str, ...]:
    """Normalise required_inputs to a tuple of non-empty strings."""
    if isinstance(value, str):
        _raise_required_inputs_value_error()
    if not isinstance(value, cabc.Iterable):
        _raise_required_inputs_value_error()
    return tuple(_normalize_non_empty_text(item, "required_inputs") for item in value)


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
        raise ValueError(msg)  # noqa: TRY004 -- normalisation reports invalid field values.
    stripped = value.strip()
    if not stripped:
        msg = f"{field_name} must be a non-empty string."
        raise ValueError(msg)
    return stripped


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
        _normalize_string_fields(self, ("action_id", "rationale"))
        object.__setattr__(
            self, "action_kind", _coerce_single_action_kind(self.action_kind)
        )
        object.__setattr__(
            self, "model_tier", _coerce_single_model_tier(self.model_tier)
        )
        object.__setattr__(
            self, "required_inputs", _normalize_required_inputs(self.required_inputs)
        )


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
    usage: LLMUsage | None
    model: str
    provider_response_id: str
    finish_reason: str | None
    provider_call_usage: ProviderCallUsage | None = None
    provider_operation: LLMProviderOperation | str = (
        LLMProviderOperation.CHAT_COMPLETIONS
    )


class ShowNotesResultAttachment(typ.Protocol):
    """Provider-neutral shape for show-notes tool result attachments."""

    @property
    def usage(self) -> LLMUsage:
        """Return token usage for the attached tool result."""
        raise NotImplementedError

    @property
    def entries(self) -> tuple[typ.Any, ...]:
        """Return show-note entries without importing generation DTOs."""
        raise NotImplementedError


class GenerationResultAttachment(typ.Protocol):
    """Provider-neutral shape for nested generation result attachments."""

    @property
    def model(self) -> str:
        """Return the provider model recorded by the nested generation result."""
        raise NotImplementedError


class GuestBiosResultAttachment(typ.Protocol):
    """Provider-neutral shape for guest-bios tool result attachments."""

    @property
    def generation_result(self) -> GenerationResultAttachment:
        """Return the nested generation result attachment."""
        raise NotImplementedError

    @property
    def sources(self) -> tuple[typ.Any, ...]:
        """Return source attachments without importing canonical DTOs."""
        raise NotImplementedError

    @property
    def tei_xml(self) -> str:
        """Return the enriched TEI payload."""
        raise NotImplementedError


@dc.dataclass(frozen=True, slots=True)
class ActionExecutionResult:
    """Typed result for one executed orchestration action."""

    action_id: str
    action_kind: ActionKind
    model_tier: ModelTier
    model: str
    summary: str
    usage: LLMUsage | None = None
    provider_call_usage: ProviderCallUsage | None = None
    provider_operation: LLMProviderOperation | str = (
        LLMProviderOperation.CHAT_COMPLETIONS
    )
    show_notes_result: ShowNotesResultAttachment | None = None
    guest_bios_result: GuestBiosResultAttachment | None = None

    def __post_init__(self) -> None:
        """Reject blank text fields and normalize enum-shaped fields."""
        for field_name in ("action_id", "model", "summary"):
            value = getattr(self, field_name)
            object.__setattr__(
                self, field_name, _normalize_non_empty_text(value, field_name)
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
