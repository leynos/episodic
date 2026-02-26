"""OpenAI adapter helpers with explicit response validation.

This module validates and normalizes OpenAI chat completion payloads at the
adapter boundary before converting them into provider-agnostic DTOs.
"""

from __future__ import annotations

import collections.abc as cabc
import typing as typ

from episodic.llm.ports import LLMResponse, LLMUsage


class OpenAIResponseValidationError(ValueError):
    """Raised when an OpenAI payload fails adapter boundary validation."""


_INVALID_CHAT_COMPLETION_MESSAGE = (
    "Invalid OpenAI chat completion payload. Expected non-empty string id/model, "
    "a non-empty choices list, and choices with message.content strings."
)
_EMPTY_CONTENT_MESSAGE = (
    "Invalid OpenAI chat completion payload. choices[0].message.content must be "
    "a non-empty string."
)
_USAGE_TOKEN_FIELDS: tuple[str, ...] = (
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
)


def _is_string_keyed_mapping(value: object) -> bool:
    """Check whether a value is a mapping with string keys."""
    return isinstance(value, cabc.Mapping) and all(
        isinstance(candidate_key, str) for candidate_key in value
    )


def _is_non_negative_int(value: object) -> bool:
    """Check whether a value is an integer token count."""
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def is_openai_usage_payload(payload: object) -> bool:
    """Validate OpenAI usage payload shape.

    Parameters
    ----------
    payload : object
        Candidate usage payload.

    Returns
    -------
    bool
        ``True`` when recognized token fields are present with non-negative
        integer values.
    """
    if not _is_string_keyed_mapping(payload):
        return False
    payload_mapping = typ.cast("cabc.Mapping[str, object]", payload)

    if not any(key in payload_mapping for key in _USAGE_TOKEN_FIELDS):
        return False

    for key in _USAGE_TOKEN_FIELDS:
        if key in payload_mapping and not _is_non_negative_int(payload_mapping[key]):
            return False
    return True


def is_openai_choice_payload(payload: object) -> bool:
    """Validate OpenAI choice payload shape.

    Parameters
    ----------
    payload : object
        Candidate choice payload.

    Returns
    -------
    bool
        ``True`` when payload contains a valid message object and optional
        finish reason.
    """
    if not _is_string_keyed_mapping(payload):
        return False
    payload_mapping = typ.cast("cabc.Mapping[str, object]", payload)

    message = payload_mapping.get("message")
    if not _is_string_keyed_mapping(message):
        return False
    message_mapping = typ.cast("cabc.Mapping[str, object]", message)

    if not isinstance(message_mapping.get("content"), str):
        return False

    if "finish_reason" not in payload_mapping:
        return True
    return isinstance(payload_mapping["finish_reason"], (str, type(None)))


def is_openai_chat_completion_payload(payload: object) -> bool:
    """Validate OpenAI chat completion payload shape.

    Parameters
    ----------
    payload : object
        Candidate chat completion payload.

    Returns
    -------
    bool
        ``True`` when required keys and nested structures are valid.
    """
    if not _is_string_keyed_mapping(payload):
        return False
    payload_mapping = typ.cast("cabc.Mapping[str, object]", payload)

    payload_id = payload_mapping.get("id")
    model = payload_mapping.get("model")
    choices = payload_mapping.get("choices")
    has_valid_identity = (
        isinstance(payload_id, str)
        and bool(payload_id.strip())
        and isinstance(model, str)
        and bool(model.strip())
    )
    has_valid_choices = (
        isinstance(choices, list)
        and bool(choices)
        and all(is_openai_choice_payload(choice) for choice in choices)
    )
    has_valid_usage = "usage" not in payload_mapping or is_openai_usage_payload(
        payload_mapping["usage"]
    )
    return has_valid_identity and has_valid_choices and has_valid_usage


def _normalize_usage(usage_payload: cabc.Mapping[str, object] | None) -> LLMUsage:
    """Convert OpenAI usage payload into provider-agnostic usage metadata."""
    if usage_payload is None:
        return LLMUsage(input_tokens=0, output_tokens=0, total_tokens=0)

    input_tokens_value = usage_payload.get("prompt_tokens", 0)
    output_tokens_value = usage_payload.get("completion_tokens", 0)
    total_tokens_value = usage_payload.get("total_tokens")

    if not _is_non_negative_int(input_tokens_value):
        raise OpenAIResponseValidationError(_INVALID_CHAT_COMPLETION_MESSAGE)
    if not _is_non_negative_int(output_tokens_value):
        raise OpenAIResponseValidationError(_INVALID_CHAT_COMPLETION_MESSAGE)
    input_tokens = typ.cast("int", input_tokens_value)
    output_tokens = typ.cast("int", output_tokens_value)

    computed_total_tokens = input_tokens + output_tokens
    if total_tokens_value is None:
        total = computed_total_tokens
    else:
        if not _is_non_negative_int(total_tokens_value):
            raise OpenAIResponseValidationError(_INVALID_CHAT_COMPLETION_MESSAGE)
        total = typ.cast("int", total_tokens_value)

    return LLMUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total,
    )


class OpenAIChatCompletionAdapter:
    """Adapter entrypoint for OpenAI chat completion payload normalization."""

    @staticmethod
    def normalize_chat_completion(payload: object) -> LLMResponse:
        """Validate and normalize a raw OpenAI chat completion payload."""
        if not is_openai_chat_completion_payload(payload):
            raise OpenAIResponseValidationError(_INVALID_CHAT_COMPLETION_MESSAGE)

        payload_mapping = typ.cast("cabc.Mapping[str, object]", payload)
        choices = typ.cast("list[object]", payload_mapping["choices"])
        first_choice = typ.cast("cabc.Mapping[str, object]", choices[0])
        message = typ.cast("cabc.Mapping[str, object]", first_choice["message"])

        generated_text = typ.cast("str", message["content"]).strip()
        if not generated_text:
            raise OpenAIResponseValidationError(_EMPTY_CONTENT_MESSAGE)

        finish_reason_value = first_choice.get("finish_reason")
        finish_reason = (
            finish_reason_value if isinstance(finish_reason_value, str) else None
        )

        usage_value = payload_mapping.get("usage")
        usage_payload = (
            typ.cast("cabc.Mapping[str, object]", usage_value)
            if _is_string_keyed_mapping(usage_value)
            else None
        )

        return LLMResponse(
            text=generated_text,
            model=typ.cast("str", payload_mapping["model"]),
            provider_response_id=typ.cast("str", payload_mapping["id"]),
            finish_reason=finish_reason,
            usage=_normalize_usage(usage_payload),
        )
