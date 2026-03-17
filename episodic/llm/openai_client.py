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
_INVALID_RESPONSES_PAYLOAD_MESSAGE = (
    "Invalid OpenAI Responses payload. Expected non-empty string id/model, "
    "a non-empty output list, and output items with content text strings."
)
_EMPTY_CONTENT_MESSAGE = (
    "Invalid OpenAI chat completion payload. choices[0].message.content must be "
    "a non-empty string."
)
_EMPTY_RESPONSES_CONTENT_MESSAGE = (
    "Invalid OpenAI Responses payload. No output_text item with non-empty text "
    "found in output content."
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


def _has_valid_identity(payload_mapping: cabc.Mapping[str, object]) -> bool:
    """Check whether payload identity fields are valid non-empty strings."""
    payload_id = payload_mapping.get("id")
    model = payload_mapping.get("model")
    return _is_non_empty_string(payload_id) and _is_non_empty_string(model)


def _has_valid_choices(payload_mapping: cabc.Mapping[str, object]) -> bool:
    """Check whether payload choices are present and structurally valid."""
    choices = payload_mapping.get("choices")
    return (
        isinstance(choices, list)
        and bool(choices)
        and all(is_openai_choice_payload(choice) for choice in choices)
    )


def _has_valid_usage(payload_mapping: cabc.Mapping[str, object]) -> bool:
    """Check whether optional payload usage metadata is valid."""
    return "usage" not in payload_mapping or is_openai_usage_payload(
        payload_mapping["usage"]
    )


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

    return (
        _has_valid_identity(payload_mapping)
        and _has_valid_choices(payload_mapping)
        and _has_valid_usage(payload_mapping)
    )


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


def _has_output_text_in_content(content: list[object]) -> bool:
    """Check whether content contains a non-empty ``output_text`` item."""
    for item in content:
        if not _is_string_keyed_mapping(item):
            continue
        item_mapping = typ.cast("cabc.Mapping[str, object]", item)
        if item_mapping.get("type") != "output_text":
            continue
        text = item_mapping.get("text")
        if _is_non_empty_string(text):
            return True
    return False


def _extract_message_content(payload_mapping: cabc.Mapping[str, object]) -> str:
    """Extract and validate stripped generated text from first choice message."""
    choices = typ.cast("list[object]", payload_mapping["choices"])
    first_choice = typ.cast("cabc.Mapping[str, object]", choices[0])
    message = typ.cast("cabc.Mapping[str, object]", first_choice["message"])
    generated_text = typ.cast("str", message["content"]).strip()
    if not generated_text:
        raise OpenAIResponseValidationError(_EMPTY_CONTENT_MESSAGE)
    return generated_text


class OpenAIChatCompletionAdapter:
    """Adapter entrypoint for OpenAI chat completion payload normalization."""

    @staticmethod
    def normalize_chat_completion(payload: object) -> LLMResponse:
        """Validate and normalize a raw OpenAI chat completion payload."""
        if not is_openai_chat_completion_payload(payload):
            raise OpenAIResponseValidationError(_INVALID_CHAT_COMPLETION_MESSAGE)

        payload_mapping = typ.cast("cabc.Mapping[str, object]", payload)
        generated_text = _extract_message_content(payload_mapping)

        choices = typ.cast("list[object]", payload_mapping["choices"])
        first_choice = typ.cast("cabc.Mapping[str, object]", choices[0])
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


def _find_output_item_with_text(
    item: object,
) -> cabc.Mapping[str, object] | None:
    """Return the item mapping if it contains an output_text content entry."""
    if not _is_string_keyed_mapping(item):
        return None
    item_mapping = typ.cast("cabc.Mapping[str, object]", item)
    content = item_mapping.get("content")
    if not isinstance(content, list) or not content:
        return None
    content_items = typ.cast("list[object]", content)
    if _has_output_text_in_content(content_items):
        return item_mapping
    return None


def _extract_first_output_mapping(
    payload_mapping: cabc.Mapping[str, object],
) -> cabc.Mapping[str, object]:
    """Validate and return the first output item containing output text."""
    output = payload_mapping.get("output")
    if not isinstance(output, list) or not output:
        raise OpenAIResponseValidationError(_INVALID_RESPONSES_PAYLOAD_MESSAGE)
    for item in output:
        candidate = _find_output_item_with_text(item)
        if candidate is not None:
            return candidate
    raise OpenAIResponseValidationError(_EMPTY_RESPONSES_CONTENT_MESSAGE)


def _extract_output_content_list(
    output_mapping: cabc.Mapping[str, object],
) -> list[object]:
    """Validate and return the content list from an output item mapping."""
    content = output_mapping.get("content")
    if not isinstance(content, list) or not content:
        raise OpenAIResponseValidationError(_INVALID_RESPONSES_PAYLOAD_MESSAGE)
    return typ.cast("list[object]", content)


def _find_output_text_in_content(content: list[object]) -> str:
    """Return the stripped text of the first output_text item in content."""
    for item in content:
        if not _is_string_keyed_mapping(item):
            continue
        item_mapping = typ.cast("cabc.Mapping[str, object]", item)
        if item_mapping.get("type") != "output_text":
            continue
        text = item_mapping.get("text")
        if _is_non_empty_string(text):
            return typ.cast("str", text).strip()
    raise OpenAIResponseValidationError(_EMPTY_RESPONSES_CONTENT_MESSAGE)


def _extract_responses_output_text(payload_mapping: cabc.Mapping[str, object]) -> str:
    """Extract assistant output text from an OpenAI Responses payload."""
    output_mapping = _extract_first_output_mapping(payload_mapping)
    content = _extract_output_content_list(output_mapping)
    return _find_output_text_in_content(content)


def _coerce_responses_usage_payload(
    payload_mapping: cabc.Mapping[str, object],
) -> cabc.Mapping[str, object] | None:
    """Extract and validate the optional usage field from a Responses payload."""
    usage_value = payload_mapping.get("usage")
    if usage_value is None:
        return None
    if _is_string_keyed_mapping(usage_value):
        return typ.cast("cabc.Mapping[str, object]", usage_value)
    raise OpenAIResponseValidationError(_INVALID_RESPONSES_PAYLOAD_MESSAGE)


class OpenAIResponsesAdapter:
    """Adapter entrypoint for OpenAI Responses payload normalization."""

    @staticmethod
    def normalize_response(payload: object) -> LLMResponse:
        """Validate and normalize a raw OpenAI Responses payload."""
        if not _is_string_keyed_mapping(payload):
            raise OpenAIResponseValidationError(_INVALID_RESPONSES_PAYLOAD_MESSAGE)

        payload_mapping = typ.cast("cabc.Mapping[str, object]", payload)
        if not _has_valid_identity(payload_mapping):
            raise OpenAIResponseValidationError(_INVALID_RESPONSES_PAYLOAD_MESSAGE)

        return LLMResponse(
            text=_extract_responses_output_text(payload_mapping),
            model=typ.cast("str", payload_mapping["model"]),
            provider_response_id=typ.cast("str", payload_mapping["id"]),
            finish_reason=typ.cast("str", payload_mapping["status"])
            if isinstance(payload_mapping.get("status"), str)
            else None,
            usage=_normalize_responses_usage(
                _coerce_responses_usage_payload(payload_mapping)
            ),
        )
