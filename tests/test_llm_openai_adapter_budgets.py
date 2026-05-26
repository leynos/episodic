"""Unit tests for OpenAI adapter token budget enforcement.

These tests exercise the adapter boundary where provider-neutral `LLMRequest`
budgets become OpenAI-compatible calls. They cover preflight estimates,
post-response provider usage checks, and the shared fixtures that simulate
provider transports without leaving the unit-test layer.
"""

import typing as typ

import httpx
import hypothesis.strategies as st
import pytest
from hypothesis import given, settings

from episodic.llm import (
    LLMProviderResponseError,
    LLMRequest,
    LLMTokenBudget,
    LLMTokenBudgetExceededError,
)
from episodic.llm.openai_adapter import _estimate_token_count

if typ.TYPE_CHECKING:
    from syrupy.assertion import SnapshotAssertion

    from openai_test_types import (
        _OpenAIAdapterFactory,
        _OpenAIJsonResponseBuilder,
        _OpenAILogSpy,
    )


@given(
    text=st.text(max_size=500),
    chars_per_token=st.floats(
        min_value=0.001,
        max_value=1_000.0,
        allow_nan=False,
        allow_infinity=False,
    ),
)
@settings(max_examples=100)
def test_estimate_token_count_matches_ceiling_ratio(
    text: str,
    chars_per_token: float,
) -> None:
    """Token estimates should preserve the configured finite positive ratio."""
    estimated_tokens = _estimate_token_count(chars_per_token, text)

    assert estimated_tokens >= 0
    if not text:
        assert estimated_tokens == 0
    else:
        assert (estimated_tokens - 1) * chars_per_token < len(text)
        assert estimated_tokens * chars_per_token >= len(text)


def _build_budget_request(*, operation: str = "chat_completions") -> LLMRequest:
    """Build a representative budgeted LLMRequest for budget tests."""
    return LLMRequest(
        model="gpt-4o-mini",
        prompt="Draft the episode opener.",
        system_prompt="Keep the output factual and concise.",
        provider_operation=operation,
        token_budget=LLMTokenBudget(
            max_input_tokens=400,
            max_output_tokens=200,
            max_total_tokens=500,
        ),
    )


@pytest.mark.asyncio
async def test_generate_rejects_prompt_that_exceeds_input_budget(
    openai_adapter_factory: _OpenAIAdapterFactory,
    openai_json_response: _OpenAIJsonResponseBuilder,
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
async def test_generate_uses_configured_chars_per_token_for_preflight_budget(
    openai_adapter_factory: _OpenAIAdapterFactory,
    openai_json_response: _OpenAIJsonResponseBuilder,
) -> None:
    """Allow operators to tighten prompt preflight estimation per adapter."""
    transport = httpx.MockTransport(lambda request: openai_json_response({}))
    async with openai_adapter_factory(
        transport=transport,
        chars_per_token=2.0,
    ) as adapter:
        with pytest.raises(LLMTokenBudgetExceededError, match="input token budget"):
            await adapter.generate(
                LLMRequest(
                    model="gpt-4o-mini",
                    prompt="x" * 41,
                    system_prompt=None,
                    token_budget=LLMTokenBudget(
                        max_input_tokens=20,
                        max_output_tokens=10,
                        max_total_tokens=40,
                    ),
                )
            )


@pytest.mark.asyncio
async def test_generate_preflight_budget_rejection_log_snapshot(
    openai_adapter_factory: _OpenAIAdapterFactory,
    openai_json_response: _OpenAIJsonResponseBuilder,
    openai_log_spy: _OpenAILogSpy,
    snapshot: SnapshotAssertion,
) -> None:
    """Preflight budget failures should emit stable structured diagnostics."""
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

    assert openai_log_spy.messages == snapshot


@pytest.mark.asyncio
async def test_generate_rejects_response_usage_that_exceeds_total_budget(
    openai_adapter_factory: _OpenAIAdapterFactory,
    openai_json_response: _OpenAIJsonResponseBuilder,
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
async def test_generate_usage_budget_rejection_log_snapshot(
    openai_adapter_factory: _OpenAIAdapterFactory,
    openai_json_response: _OpenAIJsonResponseBuilder,
    openai_log_spy: _OpenAILogSpy,
    snapshot: SnapshotAssertion,
) -> None:
    """Provider usage budget failures should emit stable structured diagnostics."""

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

    assert openai_log_spy.messages == snapshot


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
    openai_adapter_factory: _OpenAIAdapterFactory,
    openai_json_response: _OpenAIJsonResponseBuilder,
) -> None:
    """Budget enforcement requires concrete input/output usage counts."""
    async with openai_adapter_factory(
        transport=httpx.MockTransport(
            lambda _r: openai_json_response(response_payload)
        ),
        provider_operation=operation,
    ) as adapter:
        with pytest.raises(
            LLMProviderResponseError,
            match="usage",
        ):
            await adapter.generate(_build_budget_request(operation=operation))
