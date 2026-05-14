"""OpenAI chat completion payload normalization."""

import collections.abc as cabc  # noqa: TC003  # Runtime casts use mapping aliases.
import typing as typ

from episodic.llm.ports import LLMResponse

from .openai_validation import (
    _INVALID_CHAT_COMPLETION_MESSAGE,
    OpenAIResponseValidationError,
    _is_string_keyed_mapping,
    _normalize_usage,
)

_EMPTY_CONTENT_MESSAGE = (
    "Invalid OpenAI chat completion payload. choices[0].message.content must be "
    "a non-empty string."
)


def is_openai_choice_payload(payload: object) -> bool:
    """Validate OpenAI choice payload shape."""
    if not _is_string_keyed_mapping(payload):
        return False
    payload_mapping = typ.cast("cabc.Mapping[str, object]", payload)

    message = payload_mapping.get("message")
    if not _is_string_keyed_mapping(message):
        return False
    message_mapping = typ.cast("cabc.Mapping[str, object]", message)

    content = message_mapping.get("content")
    if not isinstance(content, str) or not content.strip():
        return False

    if "finish_reason" not in payload_mapping:
        return True
    return isinstance(payload_mapping["finish_reason"], (str, type(None)))


def _has_valid_identity(payload_mapping: cabc.Mapping[str, object]) -> bool:
    """Check whether payload identity fields are valid non-empty strings."""
    from .openai_validation import _has_valid_identity as shared_has_valid_identity

    return shared_has_valid_identity(payload_mapping)


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
    from .openai_validation import is_openai_usage_payload

    return "usage" not in payload_mapping or is_openai_usage_payload(
        payload_mapping["usage"]
    )


def is_openai_chat_completion_payload(payload: object) -> bool:
    """Validate OpenAI chat completion payload shape."""
    if not _is_string_keyed_mapping(payload):
        return False
    payload_mapping = typ.cast("cabc.Mapping[str, object]", payload)

    return (
        _has_valid_identity(payload_mapping)
        and _has_valid_choices(payload_mapping)
        and _has_valid_usage(payload_mapping)
    )


def _extract_message_content(payload_mapping: cabc.Mapping[str, object]) -> str:
    """Extract and validate stripped generated text from first choice message."""
    choices = typ.cast("list[object]", payload_mapping["choices"])
    first_choice = typ.cast("cabc.Mapping[str, object]", choices[0])
    message = typ.cast("cabc.Mapping[str, object]", first_choice["message"])
    generated_text = typ.cast("str", message["content"]).strip()
    if not generated_text:
        raise OpenAIResponseValidationError(_EMPTY_CONTENT_MESSAGE)
    return generated_text


def _has_blank_first_choice_message_content(payload: object) -> bool:
    """Return whether the first choice has blank message content."""
    if not _is_string_keyed_mapping(payload):
        return False
    payload_mapping = typ.cast("cabc.Mapping[str, object]", payload)
    choices = payload_mapping.get("choices")
    if not isinstance(choices, list) or not choices:
        return False
    first_choice = choices[0]
    if not _is_string_keyed_mapping(first_choice):
        return False
    choice_mapping = typ.cast("cabc.Mapping[str, object]", first_choice)
    message = choice_mapping.get("message")
    if not _is_string_keyed_mapping(message):
        return False
    message_mapping = typ.cast("cabc.Mapping[str, object]", message)
    content = message_mapping.get("content")
    return isinstance(content, str) and not content.strip()


class OpenAIChatCompletionAdapter:
    """Adapter entrypoint for OpenAI chat completion payload normalization."""

    @staticmethod
    def normalize_chat_completion(payload: object) -> LLMResponse:
        """Validate and normalize a raw OpenAI chat completion payload."""
        if not is_openai_chat_completion_payload(payload):
            if _has_blank_first_choice_message_content(payload):
                raise OpenAIResponseValidationError(_EMPTY_CONTENT_MESSAGE)
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
