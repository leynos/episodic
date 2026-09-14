"""Observability coverage for the OpenAI-compatible provider adapter."""

import itertools
import typing as typ

import httpx
import pytest

from episodic.llm import LLMTransientProviderError
from episodic.llm.ports import LLMProviderResponseError
from episodic.observability import RecordingTracer

if typ.TYPE_CHECKING:
    import collections.abc as cabc

    from openai_test_types import (
        _OpenAIAdapterFactory,
        _OpenAIJsonResponseBuilder,
        _OpenAIRequestBuilder,
    )


class _RecordingMetrics:
    """Capture bounded counters and latency observations."""

    def __init__(self) -> None:
        self.counters: list[tuple[str, dict[str, str]]] = []
        self.latencies: list[tuple[str, float, dict[str, str]]] = []

    def increment_counter(
        self,
        name: str,
        *,
        labels: cabc.Mapping[str, str],
    ) -> None:
        """Record one counter increment."""
        self.counters.append((name, dict(labels)))

    def observe_latency_ms(
        self,
        name: str,
        value: float,
        *,
        labels: cabc.Mapping[str, str],
    ) -> None:
        """Record one latency observation."""
        self.latencies.append((name, value, dict(labels)))


class _SteppingClock:
    """Return deterministic half-second monotonic steps."""

    def __init__(self) -> None:
        self._values = itertools.count(start=1.0, step=0.5)

    def monotonic_seconds(self) -> float:
        """Return the next configured timestamp."""
        return next(self._values)


def _success_payload() -> dict[str, object]:
    """Build a valid chat-completions response payload."""
    return {
        "id": "chatcmpl-observability",
        "model": "gpt-4o-mini",
        "choices": [
            {
                "message": {"content": "Draft intro copy."},
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 12,
            "completion_tokens": 7,
            "total_tokens": 19,
        },
    }


@pytest.mark.asyncio
async def test_successful_request_emits_span_counter_and_latency(
    openai_adapter_factory: _OpenAIAdapterFactory,
    openai_json_response: _OpenAIJsonResponseBuilder,
    openai_request_builder: _OpenAIRequestBuilder,
) -> None:
    """A successful provider request records one bounded success signal set."""
    tracer = RecordingTracer()
    metrics = _RecordingMetrics()

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return openai_json_response(_success_payload())

    async with openai_adapter_factory(
        transport=httpx.MockTransport(handler),
        tracer=tracer,
        metrics=metrics,
        clock=_SteppingClock(),
    ) as adapter:
        await adapter.generate(openai_request_builder())

    request_spans = [
        span for span in tracer.spans if span.name == "llm.provider_request"
    ]
    assert len(request_spans) == 1, (
        f"expected one provider request span, got {tracer.spans!r}"
    )
    assert request_spans[0].is_completed, "the provider request span must complete"
    assert request_spans[0].attributes["outcome"] == "success", (
        f"expected a success outcome, got {request_spans[0].attributes!r}"
    )
    assert metrics.counters == [
        (
            "llm.provider_request",
            {"operation": "chat_completions", "outcome": "success"},
        )
    ], f"expected one bounded success counter, got {metrics.counters!r}"
    assert metrics.latencies == [
        (
            "llm.provider_request.duration_ms",
            500.0,
            {"operation": "chat_completions", "outcome": "success"},
        )
    ], f"expected one deterministic latency observation, got {metrics.latencies!r}"


@pytest.mark.asyncio
async def test_provider_failure_emits_bounded_error_labels(
    openai_adapter_factory: _OpenAIAdapterFactory,
    openai_request_builder: _OpenAIRequestBuilder,
) -> None:
    """A non-retryable provider failure records bounded error labels."""
    tracer = RecordingTracer()
    metrics = _RecordingMetrics()

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        return httpx.Response(400, json={"error": "bad request"})

    async with openai_adapter_factory(
        transport=httpx.MockTransport(handler),
        tracer=tracer,
        metrics=metrics,
        clock=_SteppingClock(),
    ) as adapter:
        with pytest.raises(LLMProviderResponseError):
            await adapter.generate(openai_request_builder())

    span = tracer.spans[0]
    assert span.is_completed, "the failed request span must complete"
    assert span.attributes["outcome"] == "error", (
        f"expected an error outcome, got {span.attributes!r}"
    )
    assert span.attributes["failure_category"] == "provider.response_invalid", (
        f"expected the fixed failure category, got {span.attributes!r}"
    )
    assert metrics.counters == [
        (
            "llm.provider_request",
            {
                "operation": "chat_completions",
                "outcome": "error",
                "failure_category": "provider.response_invalid",
            },
        )
    ], f"expected bounded error labels, got {metrics.counters!r}"


@pytest.mark.asyncio
async def test_provider_timeout_emits_timeout_outcome(
    openai_adapter_factory: _OpenAIAdapterFactory,
    openai_request_builder: _OpenAIRequestBuilder,
) -> None:
    """A timed-out provider request records the timeout outcome."""
    tracer = RecordingTracer()
    metrics = _RecordingMetrics()

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        msg = "simulated provider timeout"
        raise httpx.ReadTimeout(msg)

    async with openai_adapter_factory(
        transport=httpx.MockTransport(handler),
        max_attempts=1,
        retry_delay_seconds=0.0,
        tracer=tracer,
        metrics=metrics,
        clock=_SteppingClock(),
    ) as adapter:
        with pytest.raises(LLMTransientProviderError):
            await adapter.generate(openai_request_builder())

    assert metrics.counters == [
        (
            "llm.provider_request",
            {
                "operation": "chat_completions",
                "outcome": "timeout",
                "failure_category": "provider.timeout",
            },
        )
    ], f"expected one bounded timeout counter, got {metrics.counters!r}"
    assert tracer.spans[0].is_completed, "the timed-out request span must complete"
    assert tracer.spans[0].attributes["failure_category"] == "provider.timeout", (
        f"expected the timeout category, got {tracer.spans[0].attributes!r}"
    )


@pytest.mark.asyncio
async def test_oversubscribed_usage_details_emit_fixed_category(
    openai_adapter_factory: _OpenAIAdapterFactory,
    openai_json_response: _OpenAIJsonResponseBuilder,
    openai_request_builder: _OpenAIRequestBuilder,
) -> None:
    """Oversubscribed usage details record the fixed validation category."""
    tracer = RecordingTracer()
    metrics = _RecordingMetrics()

    def handler(request: httpx.Request) -> httpx.Response:
        del request
        payload = _success_payload()
        usage = typ.cast("dict[str, object]", payload["usage"])
        usage["prompt_tokens_details"] = {"cached_tokens": 99}
        return openai_json_response(payload)

    async with openai_adapter_factory(
        transport=httpx.MockTransport(handler),
        tracer=tracer,
        metrics=metrics,
        clock=_SteppingClock(),
    ) as adapter:
        with pytest.raises(LLMProviderResponseError):
            await adapter.generate(openai_request_builder())

    validation_spans = [
        span for span in tracer.spans if span.name == "llm.provider_response_validation"
    ]
    assert len(validation_spans) == 1, (
        f"expected one validation span, got {tracer.spans!r}"
    )
    assert validation_spans[0].is_completed, "the validation span must complete"
    assert validation_spans[0].attributes == {
        "operation": "chat_completions",
        "outcome": "error",
        "failure_category": "provider.usage_details_invalid",
    }, (
        "the validation span must carry only bounded attributes; got "
        f"{validation_spans[0].attributes!r}"
    )
    validation_counters = [
        entry for entry in metrics.counters if entry[0] == "llm.provider_validation"
    ]
    assert validation_counters == [
        (
            "llm.provider_validation",
            {
                "operation": "chat_completions",
                "outcome": "error",
                "failure_category": "provider.usage_details_invalid",
            },
        )
    ], f"expected the fixed validation category, got {validation_counters!r}"
    for _, labels in metrics.counters:
        assert "99" not in str(labels), (
            f"raw token values must not reach metric labels: {labels!r}"
        )
