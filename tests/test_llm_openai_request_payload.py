"""Unit tests for OpenAI-compatible request payload construction."""

import pytest

from episodic.llm.openai_api.request import OpenAIPayloadOptions, _build_payload
from episodic.llm.ports import (
    LLMProviderOperation,
    LLMRequest,
    LLMTokenBudget,
)


def test_chat_payload_omits_response_format_by_default() -> None:
    """Chat payloads leave the provider response format unconstrained."""
    request = LLMRequest(model="gpt-4o-mini", prompt="Draft an intro.")

    payload = _build_payload(request, LLMProviderOperation.CHAT_COMPLETIONS)

    assert "response_format" not in payload, (
        "chat payloads must not constrain the response format by default"
    )


def test_chat_payload_requests_json_object_response() -> None:
    """JSON-parsing callers get a provider-enforced JSON object response."""
    request = LLMRequest(
        model="gpt-4o-mini",
        prompt="Draft an intro.",
        json_response=True,
    )

    payload = _build_payload(request, LLMProviderOperation.CHAT_COMPLETIONS)

    assert payload["response_format"] == {"type": "json_object"}, (
        "chat payloads must request a JSON object response when asked"
    )


def test_chat_payload_applies_provider_request_options() -> None:
    """Chat payloads carry effort, tier, and the configured token parameter."""
    request = LLMRequest(
        model="gpt-5.6-sol",
        prompt="Draft an intro.",
        token_budget=LLMTokenBudget(
            max_input_tokens=1000,
            max_output_tokens=2000,
            max_total_tokens=3000,
        ),
    )
    options = OpenAIPayloadOptions(
        reasoning_effort="low",
        service_tier="flex",
        token_limit_param="max_completion_tokens",  # noqa: S106 - parameter name, not a secret.
    )

    payload = _build_payload(
        request, LLMProviderOperation.CHAT_COMPLETIONS, options=options
    )

    assert payload["reasoning_effort"] == "low", (
        "chat payloads must carry the configured reasoning effort"
    )
    assert payload["service_tier"] == "flex", (
        "chat payloads must carry the configured service tier"
    )
    assert payload["max_completion_tokens"] == 2000, (
        "the output cap must use the configured token parameter name"
    )
    assert "max_tokens" not in payload, (
        "the default token parameter must be replaced, not duplicated"
    )


def test_payload_options_reject_unknown_token_parameter() -> None:
    """Unknown token-limit parameter names fail fast at construction."""
    with pytest.raises(ValueError, match="token_limit_param"):
        OpenAIPayloadOptions(token_limit_param="max_words")  # noqa: S106 - parameter name, not a secret.


def test_responses_payload_requests_json_object_response() -> None:
    """The Responses API shape carries the JSON format under text.format."""
    request = LLMRequest(
        model="gpt-4o-mini",
        prompt="Draft an intro.",
        json_response=True,
    )

    payload = _build_payload(request, LLMProviderOperation.RESPONSES)

    assert payload["text"] == {"format": {"type": "json_object"}}, (
        "responses payloads must request a JSON object response when asked"
    )
