"""OpenAI adapter helpers with explicit response type guards.

This module validates and normalizes OpenAI chat completion payloads at the
adapter boundary before converting them into provider-agnostic DTOs.
"""

from __future__ import annotations

import typing as typ

from episodic.llm.ports import LLMResponse, LLMUsage

type _StringKeyedObjectDict = dict[str, object]


class OpenAIUsagePayload(typ.TypedDict, total=False):
    """Subset of OpenAI token usage metadata used by Episodic."""

    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class OpenAIMessagePayload(typ.TypedDict):
    """Subset of OpenAI chat message payload used by Episodic."""

    content: str


class OpenAIChoicePayload(typ.TypedDict):
    """Subset of OpenAI chat choice payload used by Episodic."""

    message: OpenAIMessagePayload
    finish_reason: typ.NotRequired[str | None]


class OpenAIChatCompletionPayload(typ.TypedDict):
    """Subset of OpenAI chat completion payload used by Episodic."""

    id: str
    model: str
    choices: list[OpenAIChoicePayload]
    usage: typ.NotRequired[OpenAIUsagePayload]


class OpenAIResponseValidationError(ValueError):
    """Raised when an OpenAI payload fails adapter boundary validation."""


_INVALID_CHAT_COMPLETION_MESSAGE = (
    "Invalid OpenAI chat completion payload. Expected string id/model, "
    "a non-empty choices list, and choices with message.content strings."
)
_EMPTY_CONTENT_MESSAGE = (
    "Invalid OpenAI chat completion payload. choices[0].message.content must be "
    "a non-empty string."
)


def _is_string_keyed_dict(value: object) -> typ.TypeIs[_StringKeyedObjectDict]:
    """Check whether a value is a dictionary with string keys."""
    return isinstance(value, dict) and all(
        isinstance(candidate_key, str) for candidate_key in value
    )


def _is_non_negative_int(value: object) -> bool:
    """Check whether a value is an integer token count."""
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def is_openai_usage_payload(payload: object) -> typ.TypeIs[OpenAIUsagePayload]:
    """Validate OpenAI usage payload shape.

    Parameters
    ----------
    payload : object
        Candidate usage payload.

    Returns
    -------
    bool
        ``True`` when token fields are present with non-negative integer values.
    """
    if not _is_string_keyed_dict(payload):
        return False

    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        if key in payload and not _is_non_negative_int(payload[key]):
            return False
    return True


def is_openai_choice_payload(payload: object) -> typ.TypeIs[OpenAIChoicePayload]:
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
    if not _is_string_keyed_dict(payload):
        return False
    if "message" not in payload:
        return False
    if not is_openai_message_payload(payload["message"]):
        return False
    if "finish_reason" not in payload:
        return True
    return isinstance(payload["finish_reason"], str | type(None))


def is_openai_message_payload(payload: object) -> typ.TypeIs[OpenAIMessagePayload]:
    """Validate OpenAI message payload shape.

    Parameters
    ----------
    payload : object
        Candidate message payload.

    Returns
    -------
    bool
        ``True`` when a ``content`` field exists with string content.
    """
    if not _is_string_keyed_dict(payload):
        return False
    return isinstance(payload.get("content"), str)


def is_openai_chat_completion_payload(
    payload: object,
) -> typ.TypeIs[OpenAIChatCompletionPayload]:
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
    if not _is_string_keyed_dict(payload):
        return False

    choices = payload.get("choices")
    has_valid_choices = (
        isinstance(choices, list)
        and bool(choices)
        and all(is_openai_choice_payload(choice) for choice in choices)
    )
    has_valid_usage = "usage" not in payload or is_openai_usage_payload(
        payload["usage"]
    )
    return (
        isinstance(payload.get("id"), str)
        and isinstance(payload.get("model"), str)
        and has_valid_choices
        and has_valid_usage
    )


def _normalise_usage(usage_payload: OpenAIUsagePayload | None) -> LLMUsage:
    """Convert OpenAI usage payload into provider-agnostic usage metadata."""
    if usage_payload is None:
        return LLMUsage(input_tokens=0, output_tokens=0, total_tokens=0)

    input_tokens = usage_payload.get("prompt_tokens", 0)
    output_tokens = usage_payload.get("completion_tokens", 0)
    total_tokens = (
        usage_payload["total_tokens"]
        if "total_tokens" in usage_payload
        else input_tokens + output_tokens
    )
    return LLMUsage(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
    )


def normalise_openai_chat_completion(payload: object) -> LLMResponse:
    """Normalize a validated OpenAI chat completion payload.

    Parameters
    ----------
    payload : object
        Provider payload returned by the OpenAI chat completion endpoint.

    Returns
    -------
    LLMResponse
        Provider-agnostic response DTO for orchestration code.

    Raises
    ------
    OpenAIResponseValidationError
        If the payload shape is invalid or generated text content is blank.
    """
    if not is_openai_chat_completion_payload(payload):
        raise OpenAIResponseValidationError(_INVALID_CHAT_COMPLETION_MESSAGE)

    first_choice = payload["choices"][0]
    generated_text = first_choice["message"]["content"].strip()
    if not generated_text:
        raise OpenAIResponseValidationError(_EMPTY_CONTENT_MESSAGE)

    usage_payload = payload.get("usage", None)
    finish_reason = first_choice.get("finish_reason", None)
    return LLMResponse(
        text=generated_text,
        model=payload["model"],
        provider_response_id=payload["id"],
        finish_reason=finish_reason,
        usage=_normalise_usage(usage_payload),
    )


class OpenAIChatCompletionAdapter:
    """Adapter entrypoint for OpenAI chat completion payload normalization."""

    @staticmethod
    def normalise_chat_completion(payload: object) -> LLMResponse:
        """Validate and normalize a raw OpenAI chat completion payload."""
        return normalise_openai_chat_completion(payload)
