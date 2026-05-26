"""OpenAI adapter validation and token-budget helper utilities.

This module centralizes the OpenAI-compatible adapter's configuration
validation, prompt token estimation, preflight budget enforcement, provider
usage-budget validation, and structured error-event logging.

The primary utilities validate adapter configuration, estimate prompt tokens
from configured characters-per-token ratios, reject requests or responses that
exceed token budgets, and emit stable JSON error events for operator
diagnostics.

Examples
--------
Import the module and call the estimation helper when checking the heuristic
used by preflight budget validation:

>>> from episodic.llm.openai_api import utils
>>> utils._estimate_token_count(4.0, "system", "prompt")
3
"""

import dataclasses
import json
import math
import typing as typ

from episodic.llm.ports import (
    LLMProviderOperation,
    LLMProviderResponseError,
    LLMRequest,
    LLMResponse,
    LLMTokenBudget,
    LLMTokenBudgetExceededError,
)
from episodic.logging import getLogger

_log = getLogger(__name__)

type _TokenBudgetLabel = typ.Literal["input", "output", "total"]
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


class _OpenAIConfigForValidation(typ.Protocol):
    """Configuration fields required by `_validate_llm_config`."""

    @property
    def base_url(self) -> str:
        """Return the OpenAI-compatible provider base URL."""

    @property
    def api_key(self) -> str:
        """Return the provider API key."""

    @property
    def provider_operation(self) -> LLMProviderOperation | str:
        """Return the default provider operation."""

    @property
    def max_attempts(self) -> int:
        """Return the maximum retry attempts."""

    @property
    def retry_delay_seconds(self) -> float:
        """Return the retry backoff multiplier."""

    @property
    def timeout_seconds(self) -> float:
        """Return the provider request timeout."""

    @property
    def chars_per_token(self) -> float:
        """Return the preflight token-estimation divisor."""


def _operation_label(operation: LLMProviderOperation | str | None) -> str:
    """Return a stable provider-operation label for logs."""
    match operation:
        case None:
            return "default"
        case LLMProviderOperation() as value:
            return value.value
        case str() as value:
            return value
        case _:
            return str(operation)


def _log_error_event(message: str, **fields: object) -> None:
    """Emit one JSON-encoded ERROR event with bounded diagnostic fields."""
    _log.error(json.dumps({"event": message, **fields}, sort_keys=True))


def _is_positive_int(value: object) -> bool:
    """Return whether value is a positive integer, excluding booleans."""
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _is_non_negative_number(value: object) -> bool:
    """Return whether value is a finite non-negative number."""
    return (
        isinstance(value, int | float)
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value >= 0
    )


def _is_positive_number(value: object) -> bool:
    """Return whether value is a finite positive number."""
    return (
        isinstance(value, int | float)
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value > 0
    )


def _llm_config_checks(
    config: _OpenAIConfigForValidation,
    *,
    chars_per_token: object,
    is_base_url_configured: bool,
    is_api_key_configured: bool,
) -> list[tuple[bool, str, str]]:
    """Return validation checks for OpenAI-compatible adapter config."""
    chars_per_token_msg = (
        "chars_per_token must be finite and greater than zero "
        f"(got {chars_per_token!r})."
    )
    return [
        (
            not _is_positive_int(config.max_attempts),
            "max_attempts",
            "max_attempts must be greater than zero.",
        ),
        (
            not _is_non_negative_number(config.retry_delay_seconds),
            "retry_delay_seconds",
            "retry_delay_seconds must be non-negative.",
        ),
        (
            not _is_positive_number(config.timeout_seconds),
            "timeout_seconds",
            "timeout_seconds must be greater than zero.",
        ),
        (
            not _is_valid_chars_per_token(chars_per_token),
            "chars_per_token",
            chars_per_token_msg,
        ),
        (not is_base_url_configured, "base_url", "base_url must be non-empty."),
        (not is_api_key_configured, "api_key", "api_key must be non-empty."),
    ]


def _estimate_token_count(chars_per_token: float, *parts: str | None) -> int:
    """Estimate prompt tokens using a configurable chars/token heuristic.

    This heuristic approximates OpenAI/tiktoken GPT-4-era tokenization by
    returning ``ceil(len(text) / chars_per_token)`` for the combined
    non-``None`` prompt parts. Actual token counts vary by text shape,
    language, and vocabulary, so this remains a heuristic-only implementation.
    If other tokenizers need support later, this function is the extension
    point for injecting a tokenizer.
    """
    combined = "".join(part for part in parts if part is not None)
    if not combined:
        return 0
    return math.ceil(len(combined) / chars_per_token)


def _check_token_limit(actual: int, limit: int, label: str) -> None:
    """Raise when an actual usage dimension exceeds its configured limit."""
    if actual > limit:
        msg = f"Provider usage exceeded {label} token budget: {actual} > {limit}."
        raise LLMTokenBudgetExceededError(msg)


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
    """Reject requests whose estimated input tokens exceed the input budget."""
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
    """Reject requests whose projected total tokens exceed the total budget."""
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
    """Reject requests that obviously cannot fit within the configured budget."""
    estimated_input_tokens = _estimate_token_count(
        chars_per_token, request.system_prompt, request.prompt
    )
    _check_input_preflight_budget(
        estimated_input_tokens, token_budget, request, chars_per_token
    )
    _check_total_preflight_budget(
        estimated_input_tokens, token_budget, request, chars_per_token
    )


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
    """Log and reject provider usage values that exceed one budget dimension."""
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
    """Reject responses whose actual usage exceeds the configured budget."""
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


def _is_non_empty_string(value: object) -> bool:
    """Return True when *value* is a non-empty, non-whitespace string."""
    return isinstance(value, str) and bool(value.strip())


def _is_valid_chars_per_token(value: object) -> bool:
    """Return True when *value* is a finite positive number (not bool)."""
    return (
        isinstance(value, int | float)
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value > 0
    )


def _validate_llm_config(config: _OpenAIConfigForValidation) -> None:
    """Validate OpenAICompatibleLLMConfig field values."""
    base_url: object = config.base_url
    api_key: object = config.api_key
    chars_per_token: object = config.chars_per_token
    is_base_url_configured = _is_non_empty_string(base_url)
    is_api_key_configured = _is_non_empty_string(api_key)
    rejection_fields = {
        "provider_operation": _operation_label(config.provider_operation),
        "max_attempts": config.max_attempts,
        "retry_delay_seconds": config.retry_delay_seconds,
        "timeout_seconds": config.timeout_seconds,
        "chars_per_token": repr(chars_per_token),
        "base_url_configured": is_base_url_configured,
        "api_key_configured": is_api_key_configured,
    }
    for violated, field_name, msg in _llm_config_checks(
        config,
        chars_per_token=chars_per_token,
        is_base_url_configured=is_base_url_configured,
        is_api_key_configured=is_api_key_configured,
    ):
        if violated:
            _log_error_event(
                "openai_adapter.config_rejected",
                field=field_name,
                **rejection_fields,
            )
            raise ValueError(msg)
