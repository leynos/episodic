"""OpenAI-compatible LLM adapter test fixtures."""

import contextlib
import json
import typing as typ

import httpx
import pytest

from episodic.llm import (
    LLMProviderOperation,
    LLMRequest,
    LLMTokenBudget,
    OpenAICompatibleLLMAdapter,
    OpenAICompatibleLLMConfig,
)

if typ.TYPE_CHECKING:
    from openai_test_types import (
        _OpenAIAdapterFactory,
        _OpenAIInvalidConfigBuilder,
        _OpenAIJsonResponseBuilder,
        _OpenAIRequestBuilder,
    )

_OPENAI_TEST_BASE_URL = "https://example.test/v1"
_OPENAI_TEST_API_KEY = "test-key"


@pytest.fixture
def openai_request_builder() -> _OpenAIRequestBuilder:
    """Build representative OpenAI-adapter requests for unit tests."""

    def _build_request(
        *,
        operation: str | LLMProviderOperation = "chat_completions",
        prompt: str = "Draft the episode opener.",
    ) -> LLMRequest:
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

    return _build_request


@pytest.fixture
def openai_json_response() -> _OpenAIJsonResponseBuilder:
    """Build JSON HTTPX responses for OpenAI-adapter tests."""

    def _json_response(
        payload: dict[str, object],
        status_code: int = 200,
    ) -> httpx.Response:
        return httpx.Response(
            status_code=status_code,
            headers={"content-type": "application/json"},
            content=json.dumps(payload).encode("utf-8"),
        )

    return _json_response


@pytest.fixture
def openai_invalid_config_builder() -> _OpenAIInvalidConfigBuilder:
    """Build invalid OpenAI adapter configs for parametrized tests."""

    def _build_invalid_config(
        config_kwargs: dict[str, object],
    ) -> OpenAICompatibleLLMConfig:
        allowed_keys = {
            "api_key",
            "base_url",
            "max_attempts",
            "provider_operation",
            "retry_delay_seconds",
            "timeout_seconds",
        }
        unexpected_keys = set(config_kwargs) - allowed_keys
        if unexpected_keys:
            msg = (
                f"Unsupported OpenAI config override keys: {sorted(unexpected_keys)!r}"
            )
            raise ValueError(msg)
        merged_config = {
            "base_url": _OPENAI_TEST_BASE_URL,
            "api_key": _OPENAI_TEST_API_KEY,
            "timeout_seconds": 30.0,
            **config_kwargs,
        }
        return OpenAICompatibleLLMConfig(
            base_url=typ.cast("str", merged_config["base_url"]),
            api_key=typ.cast("str", merged_config["api_key"]),
            provider_operation=typ.cast(
                "str | LLMProviderOperation",
                merged_config.get("provider_operation", "chat_completions"),
            ),
            timeout_seconds=typ.cast("float", merged_config["timeout_seconds"]),
            max_attempts=typ.cast("int", merged_config.get("max_attempts", 3)),
            retry_delay_seconds=typ.cast(
                "float", merged_config.get("retry_delay_seconds", 0.5)
            ),
        )

    return _build_invalid_config


@pytest.fixture
def openai_adapter_factory() -> _OpenAIAdapterFactory:
    """Build async context managers yielding configured OpenAI adapters."""

    @contextlib.asynccontextmanager
    async def _build_adapter(  # noqa: PLR0913 - mirrors adapter override knobs in tests; see PR #49
        *,
        transport: httpx.AsyncBaseTransport,
        provider_operation: str | LLMProviderOperation = "chat_completions",
        max_attempts: int = 3,
        retry_delay_seconds: float = 0.5,
        timeout_seconds: float = 30.0,
    ) -> typ.AsyncIterator[OpenAICompatibleLLMAdapter]:
        async with httpx.AsyncClient(
            transport=transport,
            base_url=_OPENAI_TEST_BASE_URL,
        ) as client:
            yield OpenAICompatibleLLMAdapter(
                config=OpenAICompatibleLLMConfig(
                    base_url=_OPENAI_TEST_BASE_URL,
                    api_key=_OPENAI_TEST_API_KEY,
                    provider_operation=provider_operation,
                    max_attempts=max_attempts,
                    retry_delay_seconds=retry_delay_seconds,
                    timeout_seconds=timeout_seconds,
                ),
                client=client,
            )

    return _build_adapter
