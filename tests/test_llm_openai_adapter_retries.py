"""Unit tests for retry and transport behavior in the OpenAI adapter."""

import json
import typing as typ

import httpx
import pytest

from episodic.llm import LLMProviderResponseError, LLMTransientProviderError

if typ.TYPE_CHECKING:
    from openai_test_types import (
        _OpenAIAdapterFactory,
        _OpenAIJsonResponseBuilder,
        _OpenAIRequestBuilder,
    )

_CONNECT_FAILED_MESSAGE = "connect failed"
_OFFLINE_MESSAGE = "still offline"


def _static_content_handler(
    content: bytes,
) -> typ.Callable[[httpx.Request], httpx.Response]:
    """Return a handler that always responds with the given raw JSON-typed content."""

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(
            200,
            headers={"content-type": "application/json"},
            content=content,
        )

    return handler


def _make_fail_once_handler(
    first_call: typ.Callable[[httpx.Request], httpx.Response],
    second_call: typ.Callable[[httpx.Request], httpx.Response],
) -> tuple[typ.Callable[[httpx.Request], httpx.Response], list[int]]:
    """Return a (handler, counter) pair routing the first call to *first_call*.

    Routes the first call to *first_call* and every subsequent call to
    *second_call*. The counter list holds the cumulative attempt count so
    callers can assert it without ``nonlocal``.
    """
    counter: list[int] = [0]

    def handler(request: httpx.Request) -> httpx.Response:
        counter[0] += 1
        if counter[0] == 1:
            return first_call(request)
        return second_call(request)

    return handler, counter


@pytest.mark.asyncio
async def test_generate_retries_transient_failure_then_succeeds(
    openai_adapter_factory: _OpenAIAdapterFactory,
    openai_json_response: _OpenAIJsonResponseBuilder,
    openai_request_builder: _OpenAIRequestBuilder,
) -> None:
    """Retry retryable provider failures before succeeding."""
    handler, counter = _make_fail_once_handler(
        first_call=lambda r: openai_json_response(
            {"error": {"message": "rate limited"}}, 429
        ),
        second_call=lambda r: openai_json_response({
            "id": "chatcmpl-456",
            "model": "gpt-4o-mini",
            "choices": [{"message": {"content": "Recovered."}}],
            "usage": {"prompt_tokens": 20, "completion_tokens": 5, "total_tokens": 25},
        }),
    )

    async with openai_adapter_factory(
        transport=httpx.MockTransport(handler),
        max_attempts=2,
        retry_delay_seconds=0,
    ) as adapter:
        response = await adapter.generate(openai_request_builder())

    assert counter[0] == 2, "adapter should retry once after a transient 429 response"
    assert response.text == "Recovered.", (
        "adapter should return the successful retry payload text"
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [400, 404])
async def test_generate_rejects_non_retryable_http_status(
    status_code: int,
    openai_adapter_factory: _OpenAIAdapterFactory,
    openai_json_response: _OpenAIJsonResponseBuilder,
    openai_request_builder: _OpenAIRequestBuilder,
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
    openai_adapter_factory: _OpenAIAdapterFactory,
    openai_json_response: _OpenAIJsonResponseBuilder,
    openai_request_builder: _OpenAIRequestBuilder,
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
    openai_adapter_factory: _OpenAIAdapterFactory,
    openai_json_response: _OpenAIJsonResponseBuilder,
    openai_request_builder: _OpenAIRequestBuilder,
) -> None:
    """Transport failures are retried using the same transient policy as 429s."""

    def _raise_connect_error(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError(_CONNECT_FAILED_MESSAGE, request=request)

    handler, counter = _make_fail_once_handler(
        first_call=_raise_connect_error,
        second_call=lambda r: openai_json_response({
            "id": "chatcmpl-transport",
            "model": "gpt-4o-mini",
            "choices": [{"message": {"content": "Recovered after connect error."}}],
            "usage": {"prompt_tokens": 20, "completion_tokens": 6, "total_tokens": 26},
        }),
    )

    async with openai_adapter_factory(
        transport=httpx.MockTransport(handler),
        max_attempts=2,
        retry_delay_seconds=0,
    ) as adapter:
        response = await adapter.generate(openai_request_builder())

    assert counter[0] == 2, "adapter should retry once after a transport failure"
    assert response.text == "Recovered after connect error.", (
        "adapter should return the successful response after a transport retry"
    )


@pytest.mark.asyncio
async def test_generate_raises_after_exhausting_transport_retries(
    openai_adapter_factory: _OpenAIAdapterFactory,
    openai_request_builder: _OpenAIRequestBuilder,
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
    openai_adapter_factory: _OpenAIAdapterFactory,
    openai_request_builder: _OpenAIRequestBuilder,
) -> None:
    """Malformed provider JSON surfaces as a non-retryable response error."""
    async with openai_adapter_factory(
        transport=httpx.MockTransport(_static_content_handler(b"not-json"))
    ) as adapter:
        with pytest.raises(LLMProviderResponseError, match="malformed JSON"):
            await adapter.generate(openai_request_builder())


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [["not an object"], "scalar", 123])
async def test_generate_rejects_non_object_json_response(
    payload: object,
    openai_adapter_factory: _OpenAIAdapterFactory,
    openai_request_builder: _OpenAIRequestBuilder,
) -> None:
    """Non-object provider JSON payloads surface as response errors."""
    async with openai_adapter_factory(
        transport=httpx.MockTransport(
            _static_content_handler(json.dumps(payload).encode("utf-8"))
        )
    ) as adapter:
        with pytest.raises(LLMProviderResponseError, match="non-object JSON"):
            await adapter.generate(openai_request_builder())
