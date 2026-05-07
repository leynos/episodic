"""Usage aggregation helpers for generation orchestration."""

from episodic.llm import LLMUsage
from episodic.orchestration._dto import (
    ActionExecutionResult,
    GenerationOrchestrationResult,
    PlannerResult,
)


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
