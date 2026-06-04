"""Shared OpenAI payload validation helpers."""

import collections.abc as cabc
import typing as typ

from episodic.cost.ports import UsageSource
from episodic.llm.ports import LLMUsage, ProviderCallUsage


class OpenAIResponseValidationError(ValueError):
    """Raised when an OpenAI payload fails adapter boundary validation."""


_INVALID_CHAT_COMPLETION_MESSAGE = (
    "Invalid OpenAI chat completion payload. Expected non-empty string id/model, "
    "a non-empty choices list, and choices with message.content strings."
)
_INVALID_RESPONSES_PAYLOAD_MESSAGE = (
    "Invalid OpenAI Responses payload. Expected non-empty string id/model, "
    "a non-empty output list, and output items with content text strings."
)
_USAGE_TOKEN_FIELDS: tuple[str, ...] = (
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
)
_RESPONSES_USAGE_TOKEN_FIELDS: tuple[str, ...] = (
    "input_tokens",
    "output_tokens",
    "total_tokens",
)
_ZERO_LATENCY_PLACEHOLDER_MS = 0


def _is_string_keyed_mapping(value: object) -> bool:
    """Check whether a value is a mapping with string keys."""
    return isinstance(value, cabc.Mapping) and all(
        isinstance(candidate_key, str) for candidate_key in value
    )


def _is_non_negative_int(value: object) -> bool:
    """Check whether a value is an integer token count."""
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _is_non_empty_string(value: object) -> bool:
    """Check whether a value is a non-empty string."""
    return isinstance(value, str) and bool(value.strip())


def is_openai_usage_payload(payload: object) -> bool:
    """Validate OpenAI usage payload shape."""
    if not _is_string_keyed_mapping(payload):
        return False
    payload_mapping = typ.cast("cabc.Mapping[str, object]", payload)

    if not any(key in payload_mapping for key in _USAGE_TOKEN_FIELDS):
        return False

    for key in _USAGE_TOKEN_FIELDS:
        if key in payload_mapping and not _is_non_negative_int(payload_mapping[key]):
            return False
    return True


def _has_valid_identity(payload_mapping: cabc.Mapping[str, object]) -> bool:
    """Check whether payload identity fields are valid non-empty strings."""
    payload_id = payload_mapping.get("id")
    model = payload_mapping.get("model")
    return _is_non_empty_string(payload_id) and _is_non_empty_string(model)


def _validate_and_extract_token_count(
    value: object,
    field_name: str,
    error_message: str = _INVALID_CHAT_COMPLETION_MESSAGE,
) -> int:
    """Validate a token count value and return it as an integer."""
    if not _is_non_negative_int(value):
        msg = f"Invalid token count for field '{field_name}': {error_message}"
        raise OpenAIResponseValidationError(msg)
    return typ.cast("int", value)


def _resolve_total_tokens(
    input_tokens: int,
    output_tokens: int,
    total_tokens_value: object,
    error_message: str = _INVALID_CHAT_COMPLETION_MESSAGE,
) -> int:
    """Resolve total tokens from explicit value or computed sum."""
    if total_tokens_value is None:
        return input_tokens + output_tokens
    if not _is_non_negative_int(total_tokens_value):
        raise OpenAIResponseValidationError(error_message)
    return typ.cast("int", total_tokens_value)


def _extract_token_count(
    usage_payload: cabc.Mapping[str, object],
    field_name: str,
    default: int = 0,
    error_message: str = _INVALID_CHAT_COMPLETION_MESSAGE,
) -> int:
    """Extract and validate a token count field from usage payload."""
    return _validate_and_extract_token_count(
        usage_payload.get(field_name, default), field_name, error_message
    )


def _compute_total_tokens(
    usage_payload: cabc.Mapping[str, object],
    input_tokens: int,
    output_tokens: int,
    error_message: str = _INVALID_CHAT_COMPLETION_MESSAGE,
) -> int:
    """Compute total tokens from usage payload and component counts."""
    return _resolve_total_tokens(
        input_tokens,
        output_tokens,
        usage_payload.get("total_tokens"),
        error_message,
    )


def _normalize_usage(usage_payload: cabc.Mapping[str, object] | None) -> LLMUsage:
    """Convert OpenAI usage payload into provider-agnostic usage metadata."""
    if usage_payload is None:
        return LLMUsage(input_tokens=0, output_tokens=0, total_tokens=0)

    input_tokens = _extract_token_count(usage_payload, "prompt_tokens")
    output_tokens = _extract_token_count(usage_payload, "completion_tokens")
    total = _compute_total_tokens(
        usage_payload,
        input_tokens,
        output_tokens,
        _INVALID_CHAT_COMPLETION_MESSAGE,
    )

    return LLMUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total,
    )


def _normalize_responses_usage(
    usage_payload: cabc.Mapping[str, object] | None,
) -> LLMUsage:
    """Convert OpenAI Responses usage payload into provider-agnostic metadata."""
    if usage_payload is None:
        return LLMUsage(input_tokens=0, output_tokens=0, total_tokens=0)

    if not any(key in usage_payload for key in _RESPONSES_USAGE_TOKEN_FIELDS):
        raise OpenAIResponseValidationError(_INVALID_RESPONSES_PAYLOAD_MESSAGE)

    input_tokens = _extract_token_count(
        usage_payload, "input_tokens", error_message=_INVALID_RESPONSES_PAYLOAD_MESSAGE
    )
    output_tokens = _extract_token_count(
        usage_payload, "output_tokens", error_message=_INVALID_RESPONSES_PAYLOAD_MESSAGE
    )
    total = _compute_total_tokens(
        usage_payload,
        input_tokens,
        output_tokens,
        _INVALID_RESPONSES_PAYLOAD_MESSAGE,
    )
    return LLMUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total,
    )


def _extract_nested_token_count(
    usage_payload: cabc.Mapping[str, object],
    parent_key: str,
    token_key: str,
) -> int | None:
    """Extract an optional nested non-negative token count."""
    parent = usage_payload.get(parent_key)
    if parent is None:
        return None
    if not _is_string_keyed_mapping(parent):
        raise OpenAIResponseValidationError(_INVALID_CHAT_COMPLETION_MESSAGE)
    parent_mapping = typ.cast("cabc.Mapping[str, object]", parent)
    if token_key not in parent_mapping:
        return None
    return _validate_and_extract_token_count(parent_mapping[token_key], token_key)


def _add_metric_if_present(
    metrics: dict[str, int],
    key: str,
    value: int | None,
) -> None:
    """Add a canonical usage metric when the provider reported it."""
    if value is not None:
        metrics[key] = value


def _normalize_chat_provider_call_usage(
    payload_mapping: cabc.Mapping[str, object],
    usage_payload: cabc.Mapping[str, object] | None,
    finish_reason: str | None,
) -> ProviderCallUsage | None:
    """Convert OpenAI chat usage details into canonical cost metrics."""
    if usage_payload is None:
        return None
    metrics = {
        "input_tokens": _extract_token_count(usage_payload, "prompt_tokens"),
        "output_tokens": _extract_token_count(usage_payload, "completion_tokens"),
    }
    _add_metric_if_present(
        metrics,
        "cached_input_tokens",
        _extract_nested_token_count(
            usage_payload,
            "prompt_tokens_details",
            "cached_tokens",
        ),
    )
    _add_metric_if_present(
        metrics,
        "audio_input_tokens",
        _extract_nested_token_count(
            usage_payload,
            "prompt_tokens_details",
            "audio_tokens",
        ),
    )
    _add_metric_if_present(
        metrics,
        "reasoning_tokens",
        _extract_nested_token_count(
            usage_payload,
            "completion_tokens_details",
            "reasoning_tokens",
        ),
    )
    _add_metric_if_present(
        metrics,
        "audio_output_tokens",
        _extract_nested_token_count(
            usage_payload,
            "completion_tokens_details",
            "audio_tokens",
        ),
    )
    return ProviderCallUsage(
        usage_metrics=metrics,
        usage_source=UsageSource.PROVIDER,
        usage_complete=True,
        provider_response_id=typ.cast("str", payload_mapping["id"]),
        finish_reason=finish_reason,
        started_at="",
        latency_ms=_ZERO_LATENCY_PLACEHOLDER_MS,
    )


def _normalize_responses_provider_call_usage(
    payload_mapping: cabc.Mapping[str, object],
    usage_payload: cabc.Mapping[str, object] | None,
    finish_reason: str | None,
) -> ProviderCallUsage | None:
    """Convert OpenAI Responses usage details into canonical cost metrics."""
    if usage_payload is None:
        return None
    metrics = {
        "input_tokens": _extract_token_count(
            usage_payload,
            "input_tokens",
            error_message=_INVALID_RESPONSES_PAYLOAD_MESSAGE,
        ),
        "output_tokens": _extract_token_count(
            usage_payload,
            "output_tokens",
            error_message=_INVALID_RESPONSES_PAYLOAD_MESSAGE,
        ),
    }
    _add_metric_if_present(
        metrics,
        "cached_input_tokens",
        _extract_nested_token_count(
            usage_payload,
            "input_tokens_details",
            "cached_tokens",
        ),
    )
    _add_metric_if_present(
        metrics,
        "reasoning_tokens",
        _extract_nested_token_count(
            usage_payload,
            "output_tokens_details",
            "reasoning_tokens",
        ),
    )
    return ProviderCallUsage(
        usage_metrics=metrics,
        usage_source=UsageSource.PROVIDER,
        usage_complete=True,
        provider_response_id=typ.cast("str", payload_mapping["id"]),
        finish_reason=finish_reason,
        started_at="",
        latency_ms=_ZERO_LATENCY_PLACEHOLDER_MS,
    )
