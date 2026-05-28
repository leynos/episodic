"""Usage aggregation helpers for generation orchestration."""

from episodic.llm import LLMUsage
from episodic.orchestration._dto import (
    ActionExecutionResult,
    GenerationOrchestrationResult,
    PlannerResult,
)
from episodic.orchestration._types import _log_event


def _sum_usage(*usage_values: LLMUsage | None) -> LLMUsage:
    """Return the total token usage across all provided LLMUsage records."""
    input_tokens = 0
    output_tokens = 0
    reported_total_tokens = 0
    for usage in usage_values:
        if usage is None:
            continue
        input_tokens += usage.input_tokens
        output_tokens += usage.output_tokens
        reported_total_tokens += usage.total_tokens
        expected_component_total = usage.input_tokens + usage.output_tokens
        if usage.total_tokens != expected_component_total:
            _log_event(
                "warning",
                "orchestration.usage_sum.component_total_mismatch",
                input_tokens=usage.input_tokens,
                output_tokens=usage.output_tokens,
                reported_total_tokens=usage.total_tokens,
                expected_total_tokens=expected_component_total,
            )
    # Roll up totals from summed input/output counts. Provider-reported
    # total_tokens can include per-call billing adjustments, so we do not sum
    # each record's total_tokens field when building orchestration aggregates.
    derived_total_tokens = input_tokens + output_tokens
    if reported_total_tokens != derived_total_tokens:
        _log_event(
            "warning",
            "orchestration.usage_sum.aggregate_total_mismatch",
            reported_total_tokens=reported_total_tokens,
            derived_total_tokens=derived_total_tokens,
            summed_input_tokens=input_tokens,
            summed_output_tokens=output_tokens,
        )
    return LLMUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=derived_total_tokens,
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
