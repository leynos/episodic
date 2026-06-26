"""Result DTOs for generation orchestration."""

import dataclasses as dc
import typing as typ

from ._payload_dto import ActionExecutionResult, ExecutionPlan

if typ.TYPE_CHECKING:
    from episodic.llm import LLMUsage


@dc.dataclass(frozen=True, slots=True)
class GenerationOrchestrationResult:
    """Aggregated planner and tool output for one orchestration run."""

    plan: ExecutionPlan
    action_results: tuple[ActionExecutionResult, ...]
    planner_usage: LLMUsage | None
    total_usage: LLMUsage

    def __post_init__(self) -> None:
        """Freeze and validate action results supplied by callers."""
        action_results = tuple(self.action_results)
        for index, action_result in enumerate(action_results):
            if not isinstance(action_result, ActionExecutionResult):
                msg = (
                    f"action_results[{index}] must be an ActionExecutionResult; "
                    f"got {type(action_result).__name__}"
                )
                raise TypeError(msg)
        object.__setattr__(self, "action_results", action_results)
