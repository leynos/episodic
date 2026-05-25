"""Validation, estimation, and logging helpers for the OpenAI adapter."""

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


class _OpenAIConfigForValidation(typ.Protocol):
    """Configuration fields required by `_validate_llm_config`."""

    base_url: str
    api_key: str
    provider_operation: LLMProviderOperation | str
    max_attempts: int
    retry_delay_seconds: float
    timeout_seconds: float
    chars_per_token: float


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


def _validate_preflight_budget(
    request: LLMRequest,
    token_budget: LLMTokenBudget,
    chars_per_token: float,
) -> None:
    """Reject requests that obviously cannot fit within the configured budget."""
    estimated_input_tokens = _estimate_token_count(
        chars_per_token, request.system_prompt, request.prompt
    )
    if estimated_input_tokens > token_budget.max_input_tokens:
        msg = (
            "Estimated input token budget exceeded: "
            f"{estimated_input_tokens} > {token_budget.max_input_tokens}."
        )
        _log_error_event(
            "openai_adapter.preflight_budget_exceeded",
            reason="input",
            model=request.model,
            provider_operation=_operation_label(request.provider_operation),
            estimated_input_tokens=estimated_input_tokens,
            max_input_tokens=token_budget.max_input_tokens,
            max_output_tokens=token_budget.max_output_tokens,
            max_total_tokens=token_budget.max_total_tokens,
            chars_per_token=chars_per_token,
        )
        raise LLMTokenBudgetExceededError(msg)
    if token_budget.max_total_tokens is not None:
        projected_total = estimated_input_tokens + token_budget.max_output_tokens
        if projected_total > token_budget.max_total_tokens:
            msg = (
                "Estimated total token budget exceeded: "
                f"{projected_total} > {token_budget.max_total_tokens}."
            )
            _log_error_event(
                "openai_adapter.preflight_budget_exceeded",
                reason="total",
                model=request.model,
                provider_operation=_operation_label(request.provider_operation),
                estimated_input_tokens=estimated_input_tokens,
                projected_total_tokens=projected_total,
                max_input_tokens=token_budget.max_input_tokens,
                max_output_tokens=token_budget.max_output_tokens,
                max_total_tokens=token_budget.max_total_tokens,
                chars_per_token=chars_per_token,
            )
            raise LLMTokenBudgetExceededError(msg)


def _validate_usage_budget(response: LLMResponse, token_budget: LLMTokenBudget) -> None:
    """Reject responses whose actual usage exceeds the configured budget."""
    if response.usage.input_tokens > token_budget.max_input_tokens:
        msg = (
            "Provider usage exceeded input token budget: "
            f"{response.usage.input_tokens} > {token_budget.max_input_tokens}."
        )
        raise LLMTokenBudgetExceededError(msg)
    if response.usage.output_tokens > token_budget.max_output_tokens:
        msg = (
            "Provider usage exceeded output token budget: "
            f"{response.usage.output_tokens} > {token_budget.max_output_tokens}."
        )
        raise LLMTokenBudgetExceededError(msg)
    if (
        token_budget.max_total_tokens is not None
        and response.usage.total_tokens > token_budget.max_total_tokens
    ):
        msg = (
            "Provider usage exceeded total token budget: "
            f"{response.usage.total_tokens} > {token_budget.max_total_tokens}."
        )
        raise LLMTokenBudgetExceededError(msg)


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


def _validate_llm_config(config: _OpenAIConfigForValidation) -> None:
    """Validate OpenAICompatibleLLMConfig field values."""
    chars_per_token_msg = (
        "chars_per_token must be finite and greater than zero "
        f"(got {config.chars_per_token!r})."
    )
    checks: list[tuple[bool, str, str]] = [
        (
            config.max_attempts <= 0,
            "max_attempts",
            "max_attempts must be greater than zero.",
        ),
        (
            config.retry_delay_seconds < 0,
            "retry_delay_seconds",
            "retry_delay_seconds must be non-negative.",
        ),
        (
            config.timeout_seconds <= 0,
            "timeout_seconds",
            "timeout_seconds must be greater than zero.",
        ),
        (
            not math.isfinite(config.chars_per_token) or config.chars_per_token <= 0,
            "chars_per_token",
            chars_per_token_msg,
        ),
        (not config.base_url.strip(), "base_url", "base_url must be non-empty."),
        (not config.api_key.strip(), "api_key", "api_key must be non-empty."),
    ]
    for violated, field_name, msg in checks:
        if violated:
            _log_error_event(
                "openai_adapter.config_rejected",
                field=field_name,
                provider_operation=_operation_label(config.provider_operation),
                max_attempts=config.max_attempts,
                retry_delay_seconds=config.retry_delay_seconds,
                timeout_seconds=config.timeout_seconds,
                chars_per_token=repr(config.chars_per_token),
                base_url_configured=bool(config.base_url.strip()),
                api_key_configured=bool(config.api_key.strip()),
            )
            raise ValueError(msg)
