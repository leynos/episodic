"""Unit tests for the OpenAI-compatible async LLM adapter."""

import json

import httpx
import pytest

from episodic.llm import (
    LLMRequest,
    LLMTokenBudget,
    LLMTokenBudgetExceededError,
    OpenAICompatibleLLMAdapter,
    OpenAICompatibleLLMConfig,
)


def _build_request(
    *,
    operation: str = "chat_completions",
    prompt: str = "Draft the episode opener.",
) -> LLMRequest:
    """Build a representative adapter request."""
    return LLMRequest(
        model="gpt-4o-mini",
        prompt=prompt,
        system_prompt="Keep the output factual and concise.",
        provider_operation=operation,
        token_budget=LLMTokenBudget(
            max_input_tokens=400,
            max_output_tokens=200,
            max_total_tokens=500,
        ),
    )


def _json_response(
    payload: dict[str, object], status_code: int = 200
) -> httpx.Response:
    """Build an HTTPX JSON response."""
    return httpx.Response(
        status_code=status_code,
        headers={"content-type": "application/json"},
        content=json.dumps(payload).encode("utf-8"),
    )


@pytest.mark.asyncio
async def test_generate_chat_completion_success() -> None:
    """Send chat-completions payloads and normalize the provider response."""
    captured_request: httpx.Request | None = None

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_request
        captured_request = request
        return _json_response({
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
    async with httpx.AsyncClient(
        transport=transport,
        base_url="https://example.test/v1",
    ) as client:
        adapter = OpenAICompatibleLLMAdapter(
            config=OpenAICompatibleLLMConfig(
                base_url="https://example.test/v1",
                api_key="test-key",
            ),
            client=client,
        )
        response = await adapter.generate(_build_request())

    assert response.text == "Draft intro copy."
    assert response.usage.total_tokens == 60
    assert captured_request is not None
    assert captured_request.url.path == "/v1/chat/completions"
    request_body = json.loads(captured_request.content.decode("utf-8"))
    assert request_body["messages"][0]["role"] == "system"
    assert request_body["messages"][0]["content"] == (
        "Keep the output factual and concise."
    )
    assert request_body["messages"][1]["content"] == "Draft the episode opener."


@pytest.mark.asyncio
async def test_generate_responses_success() -> None:
    """Support OpenAI Responses API payload normalization."""

    def handler(request: httpx.Request) -> httpx.Response:
        return _json_response({
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
    async with httpx.AsyncClient(
        transport=transport,
        base_url="https://example.test/v1",
    ) as client:
        adapter = OpenAICompatibleLLMAdapter(
            config=OpenAICompatibleLLMConfig(
                base_url="https://example.test/v1",
                api_key="test-key",
                provider_operation="responses",
            ),
            client=client,
        )
        response = await adapter.generate(_build_request(operation="responses"))

    assert response.text == "Structured response output."
    assert response.usage.input_tokens == 15
    assert response.usage.output_tokens == 12


@pytest.mark.asyncio
async def test_generate_retries_transient_failure_then_succeeds() -> None:
    """Retry retryable provider failures before succeeding."""
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return _json_response(
                {"error": {"message": "rate limited"}},
                status_code=429,
            )
        return _json_response({
            "id": "chatcmpl-456",
            "model": "gpt-4o-mini",
            "choices": [{"message": {"content": "Recovered."}}],
            "usage": {
                "prompt_tokens": 20,
                "completion_tokens": 5,
                "total_tokens": 25,
            },
        })

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="https://example.test/v1",
    ) as client:
        adapter = OpenAICompatibleLLMAdapter(
            config=OpenAICompatibleLLMConfig(
                base_url="https://example.test/v1",
                api_key="test-key",
                max_attempts=2,
                retry_delay_seconds=0,
            ),
            client=client,
        )
        response = await adapter.generate(_build_request())

    assert attempts == 2
    assert response.text == "Recovered."


@pytest.mark.asyncio
async def test_generate_rejects_prompt_that_exceeds_input_budget() -> None:
    """Reject clearly impossible requests before calling the provider."""
    transport = httpx.MockTransport(lambda request: _json_response({}))
    async with httpx.AsyncClient(
        transport=transport,
        base_url="https://example.test/v1",
    ) as client:
        adapter = OpenAICompatibleLLMAdapter(
            config=OpenAICompatibleLLMConfig(
                base_url="https://example.test/v1",
                api_key="test-key",
            ),
            client=client,
        )
        with pytest.raises(LLMTokenBudgetExceededError, match="input token budget"):
            await adapter.generate(
                LLMRequest(
                    model="gpt-4o-mini",
                    prompt="x" * 10_000,
                    system_prompt="system",
                    token_budget=LLMTokenBudget(
                        max_input_tokens=20,
                        max_output_tokens=10,
                        max_total_tokens=40,
                    ),
                )
            )


@pytest.mark.asyncio
async def test_generate_rejects_response_usage_that_exceeds_total_budget() -> None:
    """Reject provider responses that break the configured budget."""

    def handler(request: httpx.Request) -> httpx.Response:
        return _json_response({
            "id": "chatcmpl-789",
            "model": "gpt-4o-mini",
            "choices": [{"message": {"content": "Too expensive."}}],
            "usage": {
                "prompt_tokens": 200,
                "completion_tokens": 100,
                "total_tokens": 300,
            },
        })

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="https://example.test/v1",
    ) as client:
        adapter = OpenAICompatibleLLMAdapter(
            config=OpenAICompatibleLLMConfig(
                base_url="https://example.test/v1",
                api_key="test-key",
            ),
            client=client,
        )
        with pytest.raises(LLMTokenBudgetExceededError, match="total token budget"):
            await adapter.generate(
                LLMRequest(
                    model="gpt-4o-mini",
                    prompt="Draft the episode opener.",
                    system_prompt="Keep the output factual and concise.",
                    token_budget=LLMTokenBudget(
                        max_input_tokens=400,
                        max_output_tokens=200,
                        max_total_tokens=250,
                    ),
                )
            )
