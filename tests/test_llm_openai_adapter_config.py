"""Unit tests for OpenAI adapter configuration invariants."""

import typing as typ

import pytest

from episodic.llm import LLMTokenBudget

if typ.TYPE_CHECKING:
    from openai_test_types import _OpenAIInvalidConfigBuilder


@pytest.mark.parametrize(
    ("config_kwargs", "match"),
    [
        ({"max_attempts": 0}, "max_attempts"),
        ({"retry_delay_seconds": -1}, "retry_delay_seconds"),
        ({"timeout_seconds": 0}, "timeout_seconds"),
        ({"base_url": "   "}, "base_url must be non-empty."),
        ({"api_key": "   "}, "api_key must be non-empty."),
        ({"base_url": "", "api_key": "k"}, "base_url must be non-empty."),
        ({"base_url": "http://x", "api_key": ""}, "api_key must be non-empty."),
    ],
)
def test_openai_adapter_config_rejects_invalid_values(
    config_kwargs: dict[str, object],
    match: str,
    openai_invalid_config_builder: _OpenAIInvalidConfigBuilder,
) -> None:
    """Configuration invariants should fail eagerly at construction time."""
    with pytest.raises(ValueError, match=match):
        _ = openai_invalid_config_builder(config_kwargs)


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
