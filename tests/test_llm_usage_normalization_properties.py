"""Property tests for mutually exclusive chat usage normalization."""

import typing as typ

import hypothesis.strategies as st
import pytest
from hypothesis import given, settings

from episodic.llm.openai_validation import (
    OpenAIResponseValidationError,
    _normalize_chat_provider_call_usage,
)

if typ.TYPE_CHECKING:
    import collections.abc as cabc

_TOKEN_COUNTS = st.integers(min_value=0, max_value=200)
_OPTIONAL_COUNTS = st.none() | st.integers(min_value=0, max_value=250)

type _UsageCase = tuple[int, int, int | None, int | None, int | None]

_USAGE_CASES = st.tuples(
    _TOKEN_COUNTS,
    _TOKEN_COUNTS,
    _OPTIONAL_COUNTS,
    _OPTIONAL_COUNTS,
    _OPTIONAL_COUNTS,
)


def _usage_payload(case: _UsageCase) -> dict[str, object]:
    """Build a chat usage payload with optional nested detail counts."""
    (
        prompt_tokens,
        completion_tokens,
        cached_input,
        audio_input,
        audio_output,
    ) = case
    payload: dict[str, object] = {
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": prompt_tokens + completion_tokens,
    }
    prompt_details: dict[str, int] = {}
    if cached_input is not None:
        prompt_details["cached_tokens"] = cached_input
    if audio_input is not None:
        prompt_details["audio_tokens"] = audio_input
    if prompt_details:
        payload["prompt_tokens_details"] = prompt_details
    if audio_output is not None:
        payload["completion_tokens_details"] = {"audio_tokens": audio_output}
    return payload


def _normalized_metrics(
    payload: dict[str, object],
) -> cabc.Mapping[str, int]:
    """Normalize one usage payload and return its canonical metrics."""
    usage = _normalize_chat_provider_call_usage(
        {"id": "chatcmpl-property"},
        payload,
        "stop",
    )
    assert usage is not None, "expected usage metadata for a present payload"
    return usage.usage_metrics


@given(case=_USAGE_CASES)
@settings(max_examples=100)
def test_chat_usage_metrics_partition_the_parent_totals(case: _UsageCase) -> None:
    """Valid nested details partition the parent totals exactly once."""
    (
        prompt_tokens,
        completion_tokens,
        cached_input,
        audio_input,
        audio_output,
    ) = case
    payload = _usage_payload(case)
    oversubscribed = (cached_input or 0) + (audio_input or 0) > prompt_tokens or (
        audio_output or 0
    ) > completion_tokens

    if oversubscribed:
        with pytest.raises(OpenAIResponseValidationError):
            _normalized_metrics(payload)
        return

    metrics = _normalized_metrics(payload)

    input_total = (
        metrics["input_tokens"]
        + metrics.get("cached_input_tokens", 0)
        + metrics.get("audio_input_tokens", 0)
    )
    output_total = metrics["output_tokens"] + metrics.get("audio_output_tokens", 0)
    assert input_total == prompt_tokens, (
        f"input metrics must partition prompt_tokens; got {metrics!r}"
    )
    assert output_total == completion_tokens, (
        f"output metrics must partition completion_tokens; got {metrics!r}"
    )
    assert all(value >= 0 for value in metrics.values()), (
        f"normalized metrics must be non-negative; got {metrics!r}"
    )
