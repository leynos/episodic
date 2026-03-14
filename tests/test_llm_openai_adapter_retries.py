"""Unit tests for retry and transport behavior in the OpenAI adapter."""

# ruff: noqa: ANN401

import json
import typing as typ

import httpx
import pytest

from episodic.llm import LLMProviderResponseError, LLMTransientProviderError

_CONNECT_FAILED_MESSAGE = "connect failed"
_OFFLINE_MESSAGE = "still offline"


@pytest.mark.asyncio
async def test_generate_retries_transient_failure_then_succeeds(
    openai_adapter_factory: typ.Any,
    openai_json_response: typ.Any,
    openai_request_builder: typ.Any,
) -> None:
    """Retry retryable provider failures before succeeding."""
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        del request
        attempts += 1
        if attempts == 1:
            return openai_json_response(
                {"error": {"message": "rate limited"}},
                429,
            )
        return openai_json_response({
            "id": "chatcmpl-456",
            "model": "gpt-4o-mini",
            "choices": [{"message": {"content": "Recovered."}}],
            "usage": {
                "prompt_tokens": 20,
                "completion_tokens": 5,
                "total_tokens": 25,
            },
        })

    async with openai_adapter_factory(
        transport=httpx.MockTransport(handler),
        max_attempts=2,
        retry_delay_seconds=0,
    ) as adapter:
        response = await adapter.generate(openai_request_builder())

    assert attempts == 2, "adapter should retry once after a transient 429 response"
    assert response.text == "Recovered.", (
        "adapter should return the successful retry payload text"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [400, 404])
async def test_generate_rejects_non_retryable_http_status(
    status_code: int,
    openai_adapter_factory: typ.Any,
    openai_json_response: typ.Any,
    openai_request_builder: typ.Any,
) -> None:
    """Non-retryable provider HTTP responses surface as response errors."""

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return openai_json_response(
            {"error": {"message": "bad request"}},
            status_code,
        )

    async with openai_adapter_factory(
        transport=httpx.MockTransport(handler)
    ) as adapter:
        with pytest.raises(LLMProviderResponseError, match="non-retryable"):
            await adapter.generate(openai_request_builder())


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [500, 503])
async def test_generate_retries_retryable_http_5xx_then_fails(
    status_code: int,
    openai_adapter_factory: typ.Any,
    openai_json_response: typ.Any,
    openai_request_builder: typ.Any,
) -> None:
    """Retryable 5xx provider responses exhaust retries as transient failures."""
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        del request
        attempts += 1
        return openai_json_response(
            {"error": {"message": "server error"}},
            status_code,
        )

    async with openai_adapter_factory(
        transport=httpx.MockTransport(handler),
        max_attempts=2,
        retry_delay_seconds=0,
    ) as adapter:
        with pytest.raises(LLMTransientProviderError, match="exhausting retries"):
            await adapter.generate(openai_request_builder())

    assert attempts == 2, "adapter should exhaust two attempts on retryable 5xx errors"


@pytest.mark.asyncio
async def test_generate_retries_transport_failures_then_succeeds(
    openai_adapter_factory: typ.Any,
    openai_json_response: typ.Any,
    openai_request_builder: typ.Any,
) -> None:
    """Transport failures are retried using the same transient policy as 429s."""
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise httpx.ConnectError(_CONNECT_FAILED_MESSAGE, request=request)
        return openai_json_response({
            "id": "chatcmpl-transport",
            "model": "gpt-4o-mini",
            "choices": [{"message": {"content": "Recovered after connect error."}}],
            "usage": {
                "prompt_tokens": 20,
                "completion_tokens": 6,
                "total_tokens": 26,
            },
        })

    async with openai_adapter_factory(
        transport=httpx.MockTransport(handler),
        max_attempts=2,
        retry_delay_seconds=0,
    ) as adapter:
        response = await adapter.generate(openai_request_builder())

    assert attempts == 2, "adapter should retry once after a transport failure"
    assert response.text == "Recovered after connect error.", (
        "adapter should return the successful response after a transport retry"
    )


@pytest.mark.asyncio
async def test_generate_raises_after_exhausting_transport_retries(
    openai_adapter_factory: typ.Any,
    openai_request_builder: typ.Any,
) -> None:
    """Exhausted transport retries surface as transient provider failures."""
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        raise httpx.ConnectError(_OFFLINE_MESSAGE, request=request)

    async with openai_adapter_factory(
        transport=httpx.MockTransport(handler),
        max_attempts=2,
        retry_delay_seconds=0,
    ) as adapter:
        with pytest.raises(LLMTransientProviderError, match="exhausting retries"):
            await adapter.generate(openai_request_builder())

    assert attempts == 2, "adapter should stop after the configured retry limit"


@pytest.mark.asyncio
async def test_generate_rejects_malformed_json_response(
    openai_adapter_factory: typ.Any,
    openai_request_builder: typ.Any,
) -> None:
    """Malformed provider JSON surfaces as a non-retryable response error."""

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            content=b"not-json",
        )

    async with openai_adapter_factory(
        transport=httpx.MockTransport(handler)
    ) as adapter:
        with pytest.raises(LLMProviderResponseError, match="malformed JSON"):
            await adapter.generate(openai_request_builder())


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [["not an object"], "scalar", 123])
async def test_generate_rejects_non_object_json_response(
    payload: object,
    openai_adapter_factory: typ.Any,
    openai_request_builder: typ.Any,
) -> None:
    """Non-object provider JSON payloads surface as response errors."""

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            content=json.dumps(payload).encode("utf-8"),
        )

    async with openai_adapter_factory(
        transport=httpx.MockTransport(handler)
    ) as adapter:
        with pytest.raises(LLMProviderResponseError, match="non-object JSON"):
            await adapter.generate(openai_request_builder())
