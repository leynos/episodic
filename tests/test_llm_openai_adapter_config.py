"""Unit tests for OpenAI adapter configuration invariants.

This module verifies eager validation at the adapter config and token-budget
DTO boundaries. It uses the shared invalid-config fixture so construction
rules stay aligned with the adapter factory used by behavioural LLM tests.
"""

import json
import typing as typ

import pytest

from episodic.llm import LLMTokenBudget

if typ.TYPE_CHECKING:
    from syrupy.assertion import SnapshotAssertion

    from openai_test_types import _OpenAIInvalidConfigBuilder, _OpenAILogSpy


@pytest.mark.parametrize(
    ("config_kwargs", "match"),
    [
        ({"max_attempts": 0}, "max_attempts"),
        ({"max_attempts": "3"}, "max_attempts"),
        ({"retry_delay_seconds": -1}, "retry_delay_seconds"),
        ({"retry_delay_seconds": None}, "retry_delay_seconds"),
        ({"timeout_seconds": 0}, "timeout_seconds"),
        ({"timeout_seconds": "10"}, "timeout_seconds"),
        ({"chars_per_token": 0}, "chars_per_token"),
        ({"chars_per_token": -1.0}, "chars_per_token"),
        ({"chars_per_token": float("nan")}, "chars_per_token"),
        ({"chars_per_token": float("inf")}, "chars_per_token"),
        ({"chars_per_token": "4.0"}, "chars_per_token"),
        ({"base_url": "   "}, "base_url must be non-empty."),
        ({"api_key": "   "}, "api_key must be non-empty."),
        ({"base_url": 123}, "base_url must be non-empty."),
        ({"api_key": object()}, "api_key must be non-empty."),
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


def test_openai_adapter_config_rejection_log_snapshot(
    openai_invalid_config_builder: _OpenAIInvalidConfigBuilder,
    openai_log_spy: _OpenAILogSpy,
    snapshot: SnapshotAssertion,
) -> None:
    """Rejected adapter config should emit stable structured diagnostics."""
    with pytest.raises(ValueError, match="chars_per_token"):
        _ = openai_invalid_config_builder({"chars_per_token": 0})

    assert openai_log_spy.messages == snapshot


def test_openai_adapter_config_type_rejection_logs_stable_event(
    openai_invalid_config_builder: _OpenAIInvalidConfigBuilder,
    openai_log_spy: _OpenAILogSpy,
) -> None:
    """Wrong-typed config values should use the standard rejection event."""
    with pytest.raises(ValueError, match=r"base_url must be non-empty\."):
        _ = openai_invalid_config_builder({"base_url": 123})

    payload = json.loads(openai_log_spy.messages[0])
    assert payload["event"] == "openai_adapter.config_rejected", (
        "Expected config rejection log event "
        f"'openai_adapter.config_rejected', got {payload['event']!r}."
    )
    assert payload["field"] == "base_url", (
        f"Expected rejected field 'base_url', got {payload['field']!r}."
    )
    assert payload["base_url_configured"] is False, (
        "Expected base_url_configured to be False, "
        f"got {payload['base_url_configured']!r}."
    )
    assert payload["api_key_configured"] is True, (
        "Expected api_key_configured to be True, "
        f"got {payload['api_key_configured']!r}."
    )
    assert payload["chars_per_token"] == repr(4.0), (
        "Expected chars_per_token payload value to be '4.0', "
        f"got {payload['chars_per_token']!r}."
    )


@pytest.mark.parametrize(
    ("config_kwargs", "field"),
    [
        ({"max_attempts": "3"}, "max_attempts"),
        ({"retry_delay_seconds": None}, "retry_delay_seconds"),
        ({"timeout_seconds": "10"}, "timeout_seconds"),
    ],
)
def test_openai_adapter_numeric_config_type_rejections_log_stable_event(
    config_kwargs: dict[str, object],
    field: str,
    openai_invalid_config_builder: _OpenAIInvalidConfigBuilder,
    openai_log_spy: _OpenAILogSpy,
) -> None:
    """Wrong-typed numeric config values should use the standard event."""
    with pytest.raises(ValueError, match=field):
        _ = openai_invalid_config_builder(config_kwargs)

    payload = json.loads(openai_log_spy.messages[0])
    assert payload["event"] == "openai_adapter.config_rejected", (
        "Expected config rejection log event "
        f"'openai_adapter.config_rejected', got {payload['event']!r}."
    )
    assert payload["field"] == field, (
        f"Expected config rejection field {field!r}, got {payload['field']!r}."
    )


def test_openai_invalid_config_builder_accepts_provider_operation_override(
    openai_invalid_config_builder: _OpenAIInvalidConfigBuilder,
) -> None:
    """Config-builder helper should pass through provider operation overrides."""
    config = openai_invalid_config_builder({"provider_operation": "responses"})

    assert config.provider_operation == "responses", (
        "Expected provider_operation override to be preserved by the test helper."
    )


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
