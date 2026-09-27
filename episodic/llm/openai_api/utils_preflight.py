"""OpenAI-compatible adapter preflight token-budget helpers.

This module estimates prompt tokens from a configured characters-per-token
ratio and rejects requests, before they are sent, whose estimated input or
projected total tokens would exceed the configured token budget. Rejections
emit a structured `openai_adapter.preflight_budget_exceeded` error event.
"""

import dataclasses
import math
import typing as typ

from episodic.llm.openai_api.utils_logging import _log_error_event, _operation_label
from episodic.llm.ports import LLMRequest, LLMTokenBudget, LLMTokenBudgetExceededError

type _PreflightBudgetReason = typ.Literal["input", "total"]


@dataclasses.dataclass(frozen=True, slots=True)
class _PreflightBudgetContext:
    """Preflight budget rejection details for logging and raising."""

    reason: _PreflightBudgetReason
    msg: str
    request: LLMRequest
    token_budget: LLMTokenBudget
    chars_per_token: float
    estimated_input_tokens: int
    projected_total_tokens: int | None = None


def _estimate_token_count(chars_per_token: float, *parts: str | None) -> int:
    """Estimate prompt tokens using a configurable characters-per-token ratio."""
    combined = "".join(part for part in parts if part is not None)
    if not combined:
        return 0
    token_count = math.ceil(len(combined) / chars_per_token)
    return token_count - int((token_count - 1) * chars_per_token >= len(combined))


def _raise_preflight_budget_exceeded(
    context: _PreflightBudgetContext,
) -> typ.Never:
    """Emit a structured preflight budget error event and raise."""
    token_fields: dict[str, object] = {
        "estimated_input_tokens": context.estimated_input_tokens,
    }
    if context.projected_total_tokens is not None:
        token_fields["projected_total_tokens"] = context.projected_total_tokens
    _log_error_event(
        "openai_adapter.preflight_budget_exceeded",
        reason=context.reason,
        model=context.request.model,
        provider_operation=_operation_label(context.request.provider_operation),
        max_input_tokens=context.token_budget.max_input_tokens,
        max_output_tokens=context.token_budget.max_output_tokens,
        max_total_tokens=context.token_budget.max_total_tokens,
        chars_per_token=context.chars_per_token,
        **token_fields,
    )
    raise LLMTokenBudgetExceededError(context.msg)


def _check_input_preflight_budget(
    estimated_input_tokens: int,
    token_budget: LLMTokenBudget,
    request: LLMRequest,
    chars_per_token: float,
) -> None:
    """Reject requests whose estimated input tokens exceed the input budget.

    Emits a structured ``openai_adapter.preflight_budget_exceeded`` error
    event before raising when the estimate is over the configured input limit.
    """
    if estimated_input_tokens <= token_budget.max_input_tokens:
        return

    msg = (
        "Estimated input token budget exceeded: "
        f"{estimated_input_tokens} > {token_budget.max_input_tokens}."
    )
    _raise_preflight_budget_exceeded(
        _PreflightBudgetContext(
            reason="input",
            msg=msg,
            request=request,
            token_budget=token_budget,
            chars_per_token=chars_per_token,
            estimated_input_tokens=estimated_input_tokens,
        )
    )


def _check_total_preflight_budget(
    estimated_input_tokens: int,
    token_budget: LLMTokenBudget,
    request: LLMRequest,
    chars_per_token: float,
) -> None:
    """Reject requests whose projected total tokens exceed the total budget.

    Emits a structured ``openai_adapter.preflight_budget_exceeded`` error
    event before raising when the projected input-plus-output total is over
    the configured total limit.
    """
    if token_budget.max_total_tokens is None:
        return

    projected_total = estimated_input_tokens + token_budget.max_output_tokens
    if projected_total <= token_budget.max_total_tokens:
        return

    msg = (
        "Estimated total token budget exceeded: "
        f"{projected_total} > {token_budget.max_total_tokens}."
    )
    _raise_preflight_budget_exceeded(
        _PreflightBudgetContext(
            reason="total",
            msg=msg,
            request=request,
            token_budget=token_budget,
            chars_per_token=chars_per_token,
            estimated_input_tokens=estimated_input_tokens,
            projected_total_tokens=projected_total,
        )
    )


def _validate_preflight_budget(
    request: LLMRequest,
    token_budget: LLMTokenBudget,
    chars_per_token: float,
) -> None:
    """Reject requests that obviously cannot fit within the configured budget.

    Emits structured error events through the delegated preflight checks before
    raising when either the estimated input or projected total budget is
    exceeded.
    """
    estimated_input_tokens = _estimate_token_count(
        chars_per_token, request.system_prompt, request.prompt
    )
    _check_input_preflight_budget(
        estimated_input_tokens, token_budget, request, chars_per_token
    )
    _check_total_preflight_budget(
        estimated_input_tokens, token_budget, request, chars_per_token
    )
