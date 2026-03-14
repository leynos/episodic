"""Unit tests for successful OpenAI-compatible adapter requests."""

# ruff: noqa: ANN401

import json
import typing as typ

import httpx
import pytest


@pytest.mark.asyncio
async def test_generate_chat_completion_success(
    openai_adapter_factory: typ.Any,
    openai_json_response: typ.Any,
    openai_request_builder: typ.Any,
) -> None:
    """Send chat-completions payloads and normalize the provider response."""
    captured_request: httpx.Request | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_request
        captured_request = request
        return openai_json_response({
            "id": "chatcmpl-123",
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
            },
        })

    transport = httpx.MockTransport(handler)
    async with openai_adapter_factory(transport=transport) as adapter:
        response = await adapter.generate(openai_request_builder())

    assert response.text == "Draft intro copy.", (
        "response.text should equal the normalized chat-completion content"
    )
    assert response.usage.total_tokens == 60, (
        "response usage should preserve the provider total token count"
    )
    assert captured_request is not None, "adapter should issue exactly one request"
    assert captured_request.url.path == "/v1/chat/completions", (
        "request must target /v1/chat/completions"
    )
    request_body = json.loads(captured_request.content.decode("utf-8"))
    assert request_body["messages"][0]["role"] == "system", (
        "first message must be the system prompt"
    )
    assert request_body["messages"][0]["content"] == (
        "Keep the output factual and concise."
    ), "first message must include the configured system prompt"
    assert request_body["messages"][1]["content"] == "Draft the episode opener.", (
        "second message must include the caller prompt"
    )


@pytest.mark.asyncio
async def test_generate_responses_success(
    openai_adapter_factory: typ.Any,
    openai_json_response: typ.Any,
    openai_request_builder: typ.Any,
) -> None:
    """Support OpenAI Responses API payload normalization."""

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return openai_json_response({
            "id": "resp_123",
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
            "usage": {
                "input_tokens": 15,
                "output_tokens": 12,
                "total_tokens": 27,
            },
        })

    transport = httpx.MockTransport(handler)
    async with openai_adapter_factory(
        transport=transport,
        provider_operation="responses",
    ) as adapter:
        response = await adapter.generate(openai_request_builder(operation="responses"))

    assert response.text == "Structured response output.", (
        "response.text should equal the normalized Responses output text"
    )
    assert response.usage.input_tokens == 15, (
        "Responses normalization should preserve input token counts"
    )
    assert response.usage.output_tokens == 12, (
        "Responses normalization should preserve output token counts"
    )
