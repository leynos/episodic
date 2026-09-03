"""Typed DTOs and validation helpers for generation orchestration."""

import dataclasses as dc
import uuid  # noqa: TC003 - runtime annotation inspection needs this name.

from episodic.llm import (
    LLMProviderOperation,
    LLMTokenBudget,
)

from ._payload_dto import (
    ActionExecutionResult as ActionExecutionResult,
)
from ._payload_dto import (
    ExecutionPlan as ExecutionPlan,
)
from ._payload_dto import (
    PlannedAction as PlannedAction,
)
from ._payload_dto import (
    PlannerResult as PlannerResult,
)
from ._payload_dto import (
    _coerce_action_kind as _coerce_action_kind,
)
from ._payload_dto import (
    _coerce_action_kinds as _coerce_action_kinds,
)
from ._payload_dto import (
    _coerce_model_tier as _coerce_model_tier,
)
from ._payload_dto import (
    _coerce_provider_operation as _coerce_provider_operation,
)
from ._payload_dto import (
    _coerce_single_action_kind as _coerce_single_action_kind,
)
from ._payload_dto import (
    _coerce_single_model_tier as _coerce_single_model_tier,
)
from ._payload_dto import (
    _normalize_non_empty_text as _normalize_non_empty_text,
)
from ._payload_dto import (
    _normalize_required_inputs as _normalize_required_inputs,
)
from ._payload_dto import (
    _normalize_string_fields as _normalize_string_fields,
)
from ._payload_dto import (
    _raise_required_inputs_value_error as _raise_required_inputs_value_error,
)
from ._payload_dto import (
    _require_non_empty_string as _require_non_empty_string,
)
from ._payload_dto import (
    _require_object as _require_object,
)
from ._payload_dto import (
    _require_optional_string_list as _require_optional_string_list,
)
from ._payload_dto import (
    _require_plan_step_list as _require_plan_step_list,
)
from ._types import ActionKind


@dc.dataclass(frozen=True, slots=True)
class GenerationOrchestrationRequest:
    """Typed input for one structured generation-orchestration run."""

    correlation_id: str
    script_tei_xml: str
    template_structure: dict[str, object] | None = None
    series_profile_id: uuid.UUID | None = None
    episode_id: uuid.UUID | None = None
    template_id: uuid.UUID | None = None

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


from ._checkpoint_dto import (  # noqa: E402  # Re-export after dependent DTOs exist.
    ResumeWorkflowCommand as ResumeWorkflowCommand,
)
from ._checkpoint_dto import (  # noqa: E402  # Re-export after dependent DTOs exist.
    SuspendedWorkflowResult as SuspendedWorkflowResult,
)
from ._checkpoint_dto import (  # noqa: E402  # Re-export after dependent DTOs exist.
    WorkflowCheckpoint as WorkflowCheckpoint,
)
from ._checkpoint_dto import (  # noqa: E402  # Re-export after dependent DTOs exist.
    WorkflowStepIdentity as WorkflowStepIdentity,
)
from ._checkpoint_dto import (  # noqa: E402  # Re-export after dependent DTOs exist.
    build_workflow_step_idempotency_key as build_workflow_step_idempotency_key,
)
from ._result_dto import (  # noqa: E402  # Re-export after dependent DTOs exist.
    GenerationOrchestrationResult as GenerationOrchestrationResult,
)
