"""Unit and behavioural tests for OpenAI response type guards.

These tests verify adapter boundary validation for provider payloads and
normalization into internal LLM response DTOs.
"""

from __future__ import annotations

import pytest

from episodic.llm.openai_client import (
    OpenAIChatCompletionAdapter,
    OpenAIResponseValidationError,
    is_openai_chat_completion_payload,
    is_openai_choice_payload,
    is_openai_usage_payload,
)


def _valid_chat_completion_payload() -> dict[str, object]:
    """Build a representative valid chat completion payload fixture."""
    return {
        "id": "chatcmpl_123",
        "model": "gpt-4.1-mini",
        "choices": [
            {
                "message": {"content": "Generated episode outline"},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 120,
            "completion_tokens": 35,
            "total_tokens": 155,
        },
    }


def test_usage_guard_accepts_partial_usage_payload() -> None:
    """Usage payloads may omit total token count."""
    payload: object = {"prompt_tokens": 10, "completion_tokens": 5}
    assert is_openai_usage_payload(payload), (
        "Expected usage guard to accept partial token usage payloads."
    )


def test_usage_guard_rejects_wrong_token_type() -> None:
    """Usage payloads with non-integer counts are rejected."""
    payload: object = {"prompt_tokens": "10", "completion_tokens": 5}
    assert not is_openai_usage_payload(payload), (
        "Expected usage guard to reject non-integer token usage values."
    )


@pytest.mark.parametrize("payload", [{}, {"input_tokens": 12}])
def test_usage_guard_rejects_payload_without_recognized_token_fields(
    payload: object,
) -> None:
    """Usage payloads must include at least one recognized token field."""
    assert not is_openai_usage_payload(payload), (
        "Expected usage guard to reject payloads with no recognized token fields."
    )


def test_choice_guard_accepts_message_content() -> None:
    """Choices with a message content string pass validation."""
    payload: object = {"message": {"content": "Draft content"}, "finish_reason": None}
    assert is_openai_choice_payload(payload), (
        "Expected choice guard to accept message content string payloads."
    )


def test_chat_completion_guard_rejects_missing_choices() -> None:
    """Chat completion payloads require a non-empty choices list."""
    payload: object = {"id": "chatcmpl_123", "model": "gpt-4.1-mini"}
    assert not is_openai_chat_completion_payload(payload), (
        "Expected guard to reject payloads missing choices."
    )


@pytest.mark.parametrize(
    ("field_name", "field_value"),
    [
        ("id", ""),
        ("id", "   "),
        ("model", ""),
        ("model", "   "),
    ],
)
def test_chat_completion_guard_rejects_blank_required_string_fields(
    field_name: str,
    field_value: str,
) -> None:
    """Blank identifiers and model names fail boundary validation."""
    payload = _valid_chat_completion_payload()
    payload[field_name] = field_value
    assert not is_openai_chat_completion_payload(payload), (
        "Expected guard to reject blank id/model values."
    )


def test_is_openai_chat_completion_payload_accepts_valid_payload() -> None:
    """A clearly valid payload is accepted by the type guard."""
    payload: object = _valid_chat_completion_payload()
    assert is_openai_chat_completion_payload(payload), (
        "Expected guard to accept valid chat completion payloads."
    )


def test_adapter_normalizes_valid_payload() -> None:
    """Adapter converts valid payloads into internal response DTOs."""
    adapter = OpenAIChatCompletionAdapter()

    result = adapter.normalize_chat_completion(_valid_chat_completion_payload())

    assert result.provider_response_id == "chatcmpl_123", (
        "Expected response identifier to be copied from provider payload."
    )
    assert result.model == "gpt-4.1-mini", (
        "Expected model name to be copied from provider payload."
    )
    assert result.text == "Generated episode outline", (
        "Expected adapter to map first choice message content into output text."
    )
    assert result.usage.input_tokens == 120, (
        "Expected prompt_tokens to map to input_tokens."
    )
    assert result.usage.output_tokens == 35, (
        "Expected completion_tokens to map to output_tokens."
    )
    assert result.usage.total_tokens == 155, (
        "Expected total_tokens to remain unchanged when present."
    )


def test_adapter_normalizes_partial_usage_payload() -> None:
    """Adapter derives total tokens when provider omits the total."""
    adapter = OpenAIChatCompletionAdapter()
    payload = _valid_chat_completion_payload()
    payload["usage"] = {"prompt_tokens": 7, "completion_tokens": 3}

    result = adapter.normalize_chat_completion(payload)

    assert result.usage.input_tokens == 7, (
        "Expected prompt_tokens to map to input_tokens."
    )
    assert result.usage.output_tokens == 3, (
        "Expected completion_tokens to map to output_tokens."
    )
    assert result.usage.total_tokens == 10, (
        "Expected missing total_tokens to be derived from input + output."
    )


def test_adapter_rejects_malformed_payload_with_deterministic_error() -> None:
    """Malformed payloads raise a deterministic validation error."""
    adapter = OpenAIChatCompletionAdapter()
    payload: object = {"id": 123, "model": "gpt-4.1-mini", "choices": []}

    with pytest.raises(
        OpenAIResponseValidationError,
        match=r"Invalid OpenAI chat completion payload\.",
    ):
        adapter.normalize_chat_completion(payload)


def test_adapter_rejects_blank_choice_message_content() -> None:
    """Blank message content is rejected with a deterministic validation error."""
    adapter = OpenAIChatCompletionAdapter()
    payload: object = {
        "id": "chatcmpl_123",
        "model": "gpt-4.1-mini",
        "choices": [
            {
                "message": {"content": "   "},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 120,
            "completion_tokens": 35,
            "total_tokens": 155,
        },
    }

    with pytest.raises(
        OpenAIResponseValidationError,
        match=r"choices\[0\]\.message\.content must be a non-empty string\.",
    ):
        adapter.normalize_chat_completion(payload)
