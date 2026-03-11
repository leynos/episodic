"""Unit tests for the OpenAI-compatible async LLM adapter."""

import json
import typing as typ

import httpx
import pytest

from episodic.llm import (
    LLMProviderResponseError,
    LLMRequest,
    LLMTokenBudget,
    LLMTokenBudgetExceededError,
    LLMTransientProviderError,
    OpenAICompatibleLLMAdapter,
    OpenAICompatibleLLMConfig,
)

_CONNECT_FAILED_MESSAGE = "connect failed"
_OFFLINE_MESSAGE = "still offline"


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


def _build_invalid_config(
    config_kwargs: dict[str, object],
) -> OpenAICompatibleLLMConfig:
    """Build one invalid adapter config from the parametrized kwargs."""
    if "max_attempts" in config_kwargs:
        return OpenAICompatibleLLMConfig(
            base_url="https://example.test/v1",
            api_key="test-key",
            max_attempts=typ.cast("int", config_kwargs["max_attempts"]),
        )
    if "retry_delay_seconds" in config_kwargs:
        return OpenAICompatibleLLMConfig(
            base_url="https://example.test/v1",
            api_key="test-key",
            retry_delay_seconds=typ.cast("float", config_kwargs["retry_delay_seconds"]),
        )
    return OpenAICompatibleLLMConfig(
        base_url="https://example.test/v1",
        api_key="test-key",
        timeout_seconds=typ.cast("float", config_kwargs["timeout_seconds"]),
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
@pytest.mark.parametrize("status_code", [400, 404])
async def test_generate_rejects_non_retryable_http_status(status_code: int) -> None:
    """Non-retryable provider HTTP responses surface as response errors."""

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return _json_response(
            {"error": {"message": "bad request"}},
            status_code=status_code,
        )

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
        with pytest.raises(LLMProviderResponseError, match="non-retryable"):
            await adapter.generate(_build_request())


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [500, 503])
async def test_generate_retries_retryable_http_5xx_then_fails(status_code: int) -> None:
    """Retryable 5xx provider responses exhaust retries as transient failures."""
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        del request
        attempts += 1
        return _json_response(
            {"error": {"message": "server error"}},
            status_code=status_code,
        )

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
        with pytest.raises(LLMTransientProviderError, match="exhausting retries"):
            await adapter.generate(_build_request())

    assert attempts == 2


@pytest.mark.asyncio
async def test_generate_retries_transport_failures_then_succeeds() -> None:
    """Transport failures are retried using the same transient policy as 429s."""
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise httpx.ConnectError(_CONNECT_FAILED_MESSAGE, request=request)
        return _json_response({
            "id": "chatcmpl-transport",
            "model": "gpt-4o-mini",
            "choices": [{"message": {"content": "Recovered after connect error."}}],
            "usage": {
                "prompt_tokens": 20,
                "completion_tokens": 6,
                "total_tokens": 26,
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
    assert response.text == "Recovered after connect error."


@pytest.mark.asyncio
async def test_generate_raises_after_exhausting_transport_retries() -> None:
    """Exhausted transport retries surface as transient provider failures."""
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        raise httpx.ConnectError(_OFFLINE_MESSAGE, request=request)

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
        with pytest.raises(LLMTransientProviderError, match="exhausting retries"):
            await adapter.generate(_build_request())

    assert attempts == 2


@pytest.mark.asyncio
async def test_generate_rejects_malformed_json_response() -> None:
    """Malformed provider JSON surfaces as a non-retryable response error."""

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            content=b"not-json",
        )

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
        with pytest.raises(LLMProviderResponseError, match="malformed JSON"):
            await adapter.generate(_build_request())


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [["not an object"], "scalar", 123])
async def test_generate_rejects_non_object_json_response(payload: object) -> None:
    """Non-object provider JSON payloads surface as response errors."""

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            content=json.dumps(payload).encode("utf-8"),
        )

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
        with pytest.raises(LLMProviderResponseError, match="non-object JSON"):
            await adapter.generate(_build_request())


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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("operation", "response_payload"),
    [
        (
            "chat_completions",
            {
                "id": "chatcmpl-usage-missing",
                "model": "gpt-4o-mini",
                "choices": [{"message": {"content": "No usage included."}}],
            },
        ),
        (
            "chat_completions",
            {
                "id": "chatcmpl-usage-incomplete",
                "model": "gpt-4o-mini",
                "choices": [{"message": {"content": "Only total tokens."}}],
                "usage": {"total_tokens": 10},
            },
        ),
        (
            "responses",
            {
                "id": "resp_usage_missing",
                "model": "gpt-4.1-mini",
                "output": [
                    {
                        "type": "message",
                        "content": [
                            {
                                "type": "output_text",
                                "text": "No responses usage included.",
                            }
                        ],
                    }
                ],
            },
        ),
    ],
)
async def test_generate_rejects_budgeted_responses_without_concrete_usage_counts(
    operation: str,
    response_payload: dict[str, object],
) -> None:
    """Budget enforcement requires concrete input/output usage counts."""

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return _json_response(response_payload)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="https://example.test/v1",
    ) as client:
        adapter = OpenAICompatibleLLMAdapter(
            config=OpenAICompatibleLLMConfig(
                base_url="https://example.test/v1",
                api_key="test-key",
                provider_operation=operation,
            ),
            client=client,
        )
        with pytest.raises(
            LLMProviderResponseError,
            match="usage",
        ):
            await adapter.generate(_build_request(operation=operation))


@pytest.mark.parametrize(
    ("config_kwargs", "match"),
    [
        ({"max_attempts": 0}, "max_attempts"),
        ({"retry_delay_seconds": -1}, "retry_delay_seconds"),
        ({"timeout_seconds": 0}, "timeout_seconds"),
    ],
)
def test_openai_adapter_config_rejects_invalid_values(
    config_kwargs: dict[str, object],
    match: str,
) -> None:
    """Configuration invariants should fail eagerly at construction time."""
    with pytest.raises(ValueError, match=match):
        _ = _build_invalid_config(config_kwargs)


@pytest.mark.parametrize(
    ("budget_kwargs", "match"),
    [
        ({"max_input_tokens": -1, "max_output_tokens": 1}, "max_input_tokens"),
        ({"max_input_tokens": 1, "max_output_tokens": -1}, "max_output_tokens"),
        (
            {"max_input_tokens": 1, "max_output_tokens": 1, "max_total_tokens": -1},
            "max_total_tokens",
        ),
    ],
)
def test_llm_token_budget_rejects_negative_values(
    budget_kwargs: dict[str, int],
    match: str,
) -> None:
    """Token budgets should reject negative values at construction time."""
    with pytest.raises(ValueError, match=match):
        _ = LLMTokenBudget(**budget_kwargs)
