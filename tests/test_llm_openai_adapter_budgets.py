"""Unit tests for OpenAI adapter budget enforcement."""

# ruff: noqa: ANN401

import typing as typ

import httpx
import pytest

from episodic.llm import (
    LLMProviderResponseError,
    LLMRequest,
    LLMTokenBudget,
    LLMTokenBudgetExceededError,
)


@pytest.mark.asyncio
async def test_generate_rejects_prompt_that_exceeds_input_budget(
    openai_adapter_factory: typ.Any,
    openai_json_response: typ.Any,
) -> None:
    """Reject clearly impossible requests before calling the provider."""
    transport = httpx.MockTransport(lambda request: openai_json_response({}))
    async with openai_adapter_factory(transport=transport) as adapter:
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
async def test_generate_rejects_response_usage_that_exceeds_total_budget(
    openai_adapter_factory: typ.Any,
    openai_json_response: typ.Any,
) -> None:
    """Reject provider responses that break the configured budget."""

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return openai_json_response({
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
    async with openai_adapter_factory(transport=transport) as adapter:
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
    openai_adapter_factory: typ.Any,
    openai_json_response: typ.Any,
    openai_request_builder: typ.Any,
) -> None:
    """Budget enforcement requires concrete input/output usage counts."""

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return openai_json_response(response_payload)

    transport = httpx.MockTransport(handler)
    async with openai_adapter_factory(
        transport=transport,
        provider_operation=operation,
    ) as adapter:
        with pytest.raises(
            LLMProviderResponseError,
            match="usage",
        ):
            await adapter.generate(openai_request_builder(operation=operation))
