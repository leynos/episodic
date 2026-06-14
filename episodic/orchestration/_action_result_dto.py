"""Action and planner result DTOs for generation orchestration."""

import dataclasses as dc

from episodic.generation import (
    GuestBiosEnrichmentResult,  # noqa: TC001 -- Python 3.14 lazy dataclass annotations are inspected by Hypothesis at runtime.
    ShowNotesResult,  # noqa: TC001 -- Python 3.14 lazy dataclass annotations are inspected by Hypothesis at runtime.
)
from episodic.llm import (
    LLMProviderOperation,
    LLMUsage,
    ProviderCallUsage,
)

from ._dto import ExecutionPlan, _normalize_non_empty_text
from ._types import ActionKind, ModelTier


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
    show_notes_result: ShowNotesResult | None = None
    guest_bios_result: GuestBiosEnrichmentResult | None = None

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
