"""OpenAI-compatible adapter provider usage-budget helpers.

This module validates provider-reported usage counts against the
configured token budget, and requires concrete input/output usage counts on
provider responses so budget enforcement has values to check. Rejections
emit a structured `openai_adapter.usage_budget_exceeded` error event.
"""

import typing as typ

from episodic.llm.openai_api.utils_logging import _log_error_event, _operation_label
from episodic.llm.ports import (
    LLMProviderOperation,
    LLMProviderResponseError,
    LLMResponse,
    LLMTokenBudget,
    LLMTokenBudgetExceededError,
)

type _TokenBudgetLabel = typ.Literal["input", "output", "total"]


def _check_token_limit(actual: int, limit: int, label: str) -> None:
    """Raise when an actual usage dimension exceeds its configured limit."""
    if actual > limit:
        msg = f"Provider usage exceeded {label} token budget: {actual} > {limit}."
        raise LLMTokenBudgetExceededError(msg)


def _usage_values_for_label(
    response: LLMResponse,
    token_budget: LLMTokenBudget,
) -> dict[_TokenBudgetLabel, tuple[int, int | None]]:
    """Return actual and budgeted usage values keyed by token dimension."""
    return {
        "input": (response.usage.input_tokens, token_budget.max_input_tokens),
        "output": (response.usage.output_tokens, token_budget.max_output_tokens),
        "total": (response.usage.total_tokens, token_budget.max_total_tokens),
    }


def _check_usage_budget(
    label: _TokenBudgetLabel,
    response: LLMResponse,
    token_budget: LLMTokenBudget,
    operation: LLMProviderOperation,
) -> None:
    """Log and reject provider usage values that exceed one budget dimension.

    Emits ``openai_adapter.usage_budget_exceeded`` with normalized usage and
    limit fields before raising when the selected usage dimension exceeds its
    configured budget.
    """
    actual, limit = _usage_values_for_label(response, token_budget)[label]
    if limit is None:
        return
    if actual <= limit:
        return

    _log_error_event(
        "openai_adapter.usage_budget_exceeded",
        reason=label,
        model=response.model,
        provider_operation=_operation_label(operation),
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
        total_tokens=response.usage.total_tokens,
        max_input_tokens=token_budget.max_input_tokens,
        max_output_tokens=token_budget.max_output_tokens,
        max_total_tokens=token_budget.max_total_tokens,
    )
    _check_token_limit(actual, limit, label)


def _validate_usage_budget(
    response: LLMResponse,
    token_budget: LLMTokenBudget,
    operation: LLMProviderOperation,
) -> None:
    """Reject responses whose actual usage exceeds the configured budget.

    Emits structured usage-budget error events through the delegated dimension
    checks before raising when provider-reported usage is over any configured
    input, output, or total limit.
    """
    _check_usage_budget(
        "input",
        response,
        token_budget,
        operation,
    )
    _check_usage_budget(
        "output",
        response,
        token_budget,
        operation,
    )
    _check_usage_budget(
        "total",
        response,
        token_budget,
        operation,
    )


def _has_non_negative_int_mapping_value(
    payload: dict[str, object],
    field_name: str,
) -> bool:
    """Check whether a mapping field contains a non-negative integer."""
    value = payload.get(field_name)
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _require_concrete_usage_counts(
    payload: dict[str, object],
    operation: LLMProviderOperation,
) -> None:
    """Require concrete input/output usage counts for budget enforcement."""
    usage = payload.get("usage")
    if not isinstance(usage, dict):
        msg = "Provider response omitted concrete usage counts required for budgets."
        raise LLMProviderResponseError(msg)
    usage_mapping = typ.cast("dict[str, object]", usage)

    required_fields = (
        ("prompt_tokens", "completion_tokens")
        if operation is LLMProviderOperation.CHAT_COMPLETIONS
        else ("input_tokens", "output_tokens")
    )
    if not all(
        _has_non_negative_int_mapping_value(usage_mapping, field)
        for field in required_fields
    ):
        msg = "Provider response usage must include concrete input/output token counts."
        raise LLMProviderResponseError(msg)
