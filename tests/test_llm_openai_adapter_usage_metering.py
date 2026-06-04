"""Tests for OpenAI-compatible provider-call usage metadata."""

import typing as typ

import httpx
import pytest

from episodic.cost import UsageSource

if typ.TYPE_CHECKING:
    from openai_test_types import (
        _OpenAIAdapterFactory,
        _OpenAIJsonResponseBuilder,
        _OpenAIRequestBuilder,
    )


@pytest.mark.asyncio
async def test_chat_completion_provider_call_usage_includes_cached_tokens(
    openai_adapter_factory: _OpenAIAdapterFactory,
    openai_json_response: _OpenAIJsonResponseBuilder,
    openai_request_builder: _OpenAIRequestBuilder,
) -> None:
    """Chat-completions usage details populate canonical cost metrics."""

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return openai_json_response({
            "id": "chatcmpl-usage",
            "model": "gpt-4o-mini",
            "choices": [
                {
                    "message": {"content": "Draft intro copy."},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": 42,
                "completion_tokens": 18,
                "total_tokens": 60,
                "prompt_tokens_details": {"cached_tokens": 11, "audio_tokens": 3},
                "completion_tokens_details": {
                    "reasoning_tokens": 7,
                    "audio_tokens": 5,
                },
            },
        })

    async with openai_adapter_factory(
        transport=httpx.MockTransport(handler)
    ) as adapter:
        response = await adapter.generate(openai_request_builder())

    assert response.provider_call_usage is not None, (
        "provider_call_usage should not be None"
    )
    assert response.provider_call_usage.usage_source is UsageSource.PROVIDER, (
        "expected UsageSource.PROVIDER"
    )
    assert response.provider_call_usage.usage_complete is True, (
        "expected usage_complete True"
    )
    assert response.provider_call_usage.provider_response_id == "chatcmpl-usage", (
        "unexpected provider_response_id"
    )
    assert response.provider_call_usage.finish_reason == "stop", (
        "unexpected finish_reason"
    )
    assert response.provider_call_usage.usage_metrics == {
        "input_tokens": 42,
        "output_tokens": 18,
        "cached_input_tokens": 11,
        "audio_input_tokens": 3,
        "reasoning_tokens": 7,
        "audio_output_tokens": 5,
    }, f"usage_metrics mismatch: {response.provider_call_usage.usage_metrics}"


@pytest.mark.asyncio
async def test_responses_provider_call_usage_includes_reasoning_tokens(
    openai_adapter_factory: _OpenAIAdapterFactory,
    openai_json_response: _OpenAIJsonResponseBuilder,
    openai_request_builder: _OpenAIRequestBuilder,
) -> None:
    """Responses usage details populate canonical cost metrics."""

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return openai_json_response({
            "id": "resp_usage",
            "model": "gpt-4.1-mini",
            "output": [
                {
                    "type": "message",
                    "content": [
                        {
                            "type": "output_text",
                            "text": "Structured response output.",
                        }
                    ],
                }
            ],
            "status": "completed",
            "usage": {
                "input_tokens": 15,
                "output_tokens": 12,
                "total_tokens": 27,
                "input_tokens_details": {"cached_tokens": 4},
                "output_tokens_details": {"reasoning_tokens": 6},
            },
        })

    async with openai_adapter_factory(
        transport=httpx.MockTransport(handler),
        provider_operation="responses",
    ) as adapter:
        response = await adapter.generate(openai_request_builder(operation="responses"))

    assert response.provider_call_usage is not None, (
        "expected provider_call_usage to be present on response"
    )
    assert response.provider_call_usage.usage_metrics == {
        "input_tokens": 15,
        "output_tokens": 12,
        "cached_input_tokens": 4,
        "reasoning_tokens": 6,
    }, f"unexpected usage_metrics: {response.provider_call_usage.usage_metrics}"
