"""Async OpenAI-compatible LLM port adapter.

This module implements the concrete outbound `LLMPort` used for
OpenAI-compatible HTTP providers. It composes the sibling `request` module for
operation-specific paths and payloads, the `response` module for HTTP status
handling and payload normalization, and `utils` for configuration validation,
token-budget checks, usage validation, and structured error logging.

`OpenAICompatibleLLMAdapter.generate()` is the adapter boundary: it validates
the provider-neutral `LLMRequest`, sends the provider request with bounded
retries, normalizes the provider payload into `LLMResponse`, and enforces the
configured token budget before returning to application code.
"""

import dataclasses as dc
import typing as typ

import httpx
from tenacity import (
    AsyncRetrying,
    RetryError,
    retry_if_exception_type,
    stop_after_attempt,
    wait_random_exponential,
)

from episodic.llm.openai_api.request import (
    OpenAIPayloadOptions,
    _build_payload,
    _coerce_operation,
    _path_for_operation,
)
from episodic.llm.openai_api.response import (
    _check_http_status,
    _decode_json_response,
    _normalize_payload,
)
from episodic.llm.openai_api.utils import (
    _log_error_event,
    _require_concrete_usage_counts,
    _validate_llm_config,
    _validate_preflight_budget,
    _validate_usage_budget,
)
from episodic.llm.openai_validation import OpenAIUsageDetailError
from episodic.llm.ports import (
    LLMPort,
    LLMProviderOperation,
    LLMProviderResponseError,
    LLMRequest,
    LLMResponse,
    LLMTransientProviderError,
)
from episodic.observability import (
    MetricsPort,
    MonotonicClockPort,
    NoopMetrics,
    NoopTracer,
    PerfCounterClock,
    TracerPort,
)

if typ.TYPE_CHECKING:
    from types import TracebackType


@dc.dataclass(frozen=True, slots=True)
class OpenAICompatibleLLMConfig:
    """Configuration for the OpenAI-compatible HTTP adapter.

    Parameters
    ----------
    base_url
        Base provider URL, without an operation path. The adapter strips a
        trailing slash before appending OpenAI-compatible endpoint paths.
    api_key
        Bearer token used for provider HTTP requests.
    provider_operation
        Default operation shape to use when a request does not set
        ``provider_operation``. Accepts ``LLMProviderOperation`` values or their
        string values.
    max_attempts
        Maximum number of attempts for transient HTTP and transport failures.
    retry_delay_seconds
        Exponential backoff multiplier, in seconds, used between retry
        attempts.
    timeout_seconds
        Per-request HTTP timeout, in seconds.
    chars_per_token
        Positive finite character-per-token divisor used for preflight prompt
        budget estimation. For example, ``4.0`` estimates one token per four
        prompt characters.

    Raises
    ------
    ValueError
        Raised by ``_validate_llm_config`` when any configuration value is
        missing, has the wrong type, or violates the supported numeric bounds.
    """

    base_url: str
    api_key: str
    provider_operation: LLMProviderOperation | str = (
        LLMProviderOperation.CHAT_COMPLETIONS
    )
    max_attempts: int = 3
    retry_delay_seconds: float = 0.5
    timeout_seconds: float = 30.0
    chars_per_token: float = 4.0
    # Optional provider-specific request options; see OpenAIPayloadOptions.
    reasoning_effort: str | None = None
    service_tier: str | None = None
    token_limit_param: str = "max_tokens"  # noqa: S105 - parameter name, not a secret.

    __post_init__ = _validate_llm_config


class OpenAICompatibleLLMAdapter(LLMPort):
    """Call an OpenAI-compatible HTTP endpoint.

    Parameters
    ----------
    config
        Validated adapter configuration. Its retry, timeout, operation, and
        token-estimation settings are copied into the adapter at construction.
    client
        Optional ``httpx.AsyncClient`` supplied by the caller. When omitted, the
        adapter creates its own client and sets ``_owns_client`` to ``True``.
        When supplied, ``_owns_client`` is ``False`` and caller-owned client
        lifecycle remains outside the adapter.

    Raises
    ------
    ValueError
        Propagates validation failures raised while constructing
        ``OpenAICompatibleLLMConfig``.
    LLMProviderResponseError
        Raised when the configured provider operation is unsupported.
    """

    def __init__(  # noqa: PLR0913  # pylint: disable=too-many-arguments  # Observability ports travel together through the runtime seam.
        self,
        *,
        config: OpenAICompatibleLLMConfig,
        client: httpx.AsyncClient | None = None,
        tracer: TracerPort | None = None,
        metrics: MetricsPort | None = None,
        clock: MonotonicClockPort | None = None,
    ) -> None:
        self._tracer: TracerPort = tracer if tracer is not None else NoopTracer()
        self._metrics: MetricsPort = metrics if metrics is not None else NoopMetrics()
        self._clock: MonotonicClockPort = (
            clock if clock is not None else PerfCounterClock()
        )
        self._base_url = config.base_url.rstrip("/")
        self._api_key = config.api_key
        self._provider_operation = _coerce_operation(config.provider_operation)
        self._client = client if client is not None else httpx.AsyncClient()
        self._owns_client = client is None
        self._max_attempts = config.max_attempts
        self._retry_delay_seconds = config.retry_delay_seconds
        self._timeout_seconds = config.timeout_seconds
        self._chars_per_token = config.chars_per_token
        # OpenAIPayloadOptions validates token_limit_param at construction.
        self._payload_options = OpenAIPayloadOptions(
            reasoning_effort=config.reasoning_effort,
            service_tier=config.service_tier,
            token_limit_param=config.token_limit_param,
        )

    async def __aenter__(self) -> OpenAICompatibleLLMAdapter:
        """Return the adapter for use as an async context manager.

        Returns
        -------
        OpenAICompatibleLLMAdapter
            The current adapter instance. The paired ``__aexit__`` call closes
            only adapter-owned HTTP clients.
        """
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Close owned HTTP resources when leaving the adapter context."""
        del exc_type, exc, traceback
        await self.aclose()

    async def aclose(self) -> None:
        """Close the adapter-owned HTTP client when present.

        The method is a no-op for caller-supplied clients because
        ``_owns_client`` is ``False`` in that case.
        """
        if self._owns_client:
            await self._client.aclose()

    async def generate(self, request: LLMRequest) -> LLMResponse:
        """Generate text from an OpenAI-compatible provider.

        Parameters
        ----------
        request
            Provider-neutral request containing model, prompts, optional token
            budget, and optional provider operation override. Token budgets use
            ``chars_per_token`` for preflight input estimation before the HTTP
            call.

        Returns
        -------
        LLMResponse
            Normalized provider text and concrete usage counts.

        Raises
        ------
        LLMProviderResponseError
            If the requested operation is unsupported, the provider returns a
            non-retryable error or malformed response, or response
            normalization fails.
        LLMTransientProviderError
            If transient provider failures exhaust the configured retries.
        LLMTokenBudgetExceededError
            If preflight validation or provider-reported usage exceeds the
            request token budget.
        """  # noqa: DOC502  # Documents exceptions propagated by collaborators.
        token_budget = request.token_budget
        if token_budget is not None:
            _validate_preflight_budget(request, token_budget, self._chars_per_token)

        operation = _coerce_operation(
            self._provider_operation
            if request.provider_operation is None
            else request.provider_operation
        )
        response_payload = await self._send_with_retries(
            path=_path_for_operation(operation),
            payload=_build_payload(request, operation, options=self._payload_options),
            operation_value=operation.value,
        )
        with self._tracer.start_span(
            "llm.provider_response_validation",
            attributes={"operation": operation.value},
        ) as span:
            try:
                if token_budget is not None:
                    _require_concrete_usage_counts(response_payload, operation)
                response = _normalize_payload(response_payload, operation)
            except LLMProviderResponseError as exc:
                failure_category = (
                    "provider.usage_details_invalid"
                    if isinstance(exc.__cause__, OpenAIUsageDetailError)
                    else "provider.response_invalid"
                )
                span.set_attribute("outcome", "error")
                span.set_attribute("failure_category", failure_category)
                self._metrics.increment_counter(
                    "llm.provider_validation",
                    labels={
                        "operation": operation.value,
                        "outcome": "error",
                        "failure_category": failure_category,
                    },
                )
                raise
            span.set_attribute("outcome", "success")

        if token_budget is not None:
            _validate_usage_budget(response, token_budget, operation)
        return response

    async def _send_with_retries(
        self,
        *,
        path: str,
        payload: dict[str, object],
        operation_value: str,
    ) -> dict[str, object]:
        """Send a provider request with retry handling for transient failures."""
        try:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(self._max_attempts),
                wait=wait_random_exponential(
                    multiplier=self._retry_delay_seconds,
                    max=self._retry_delay_seconds * 16,
                ),
                retry=retry_if_exception_type((
                    httpx.TransportError,
                    LLMTransientProviderError,
                )),
                reraise=False,
            ):
                with attempt:
                    return await self._send_once(
                        path=path,
                        payload=payload,
                        operation_value=operation_value,
                    )
        except RetryError as exc:
            last = exc.last_attempt.exception()
            _log_error_event(
                "openai_adapter.retries_exhausted",
                max_attempts=self._max_attempts,
                last_error_type=type(last).__name__ if last is not None else "unknown",
            )
            msg = "Transient provider failure after exhausting retries."
            raise LLMTransientProviderError(msg) from exc
        # Unreachable: AsyncRetrying always raises RetryError on exhaustion
        # when reraise=False. Guard satisfies ty's return-type analysis.
        msg = "unreachable: tenacity retry loop exhausted"
        raise AssertionError(msg)

    async def _send_once(
        self,
        *,
        path: str,
        payload: dict[str, object],
        operation_value: str,
    ) -> dict[str, object]:
        """Send one instrumented provider request and decode its payload.

        Each attempt emits one span, one bounded outcome counter, and one
        latency observation. Labels stay bounded: no attempt identifiers,
        payloads, or credentials are recorded.

        Returns
        -------
        dict[str, object]
            Decoded JSON payload of a successful provider response.

        Raises
        ------
        httpx.TimeoutException
            If the provider request exceeds the configured timeout.
        httpx.TransportError
            If the HTTP transport fails before a response arrives.
        LLMTransientProviderError
            If the provider returns a retryable HTTP status.
        LLMProviderResponseError
            If the provider returns a non-retryable or malformed response.
        """
        started = self._clock.monotonic_seconds()
        outcome = "success"
        failure_category: str | None = None
        with self._tracer.start_span(
            "llm.provider_request",
            attributes={"operation": operation_value},
        ) as span:
            try:
                response = await self._client.post(
                    f"{self._base_url}{path}",
                    json=payload,
                    headers={
                        "authorization": f"Bearer {self._api_key}",
                        "content-type": "application/json",
                    },
                    timeout=self._timeout_seconds,
                )
                _check_http_status(response)
                return _decode_json_response(response)
            except httpx.TimeoutException:
                outcome, failure_category = "timeout", "provider.timeout"
                raise
            except httpx.TransportError, LLMTransientProviderError:
                outcome, failure_category = "retry", "provider.transient"
                raise
            except LLMProviderResponseError:
                outcome, failure_category = "error", "provider.response_invalid"
                raise
            finally:
                span.set_attribute("outcome", outcome)
                labels = {"operation": operation_value, "outcome": outcome}
                if failure_category is not None:
                    span.set_attribute("failure_category", failure_category)
                    labels["failure_category"] = failure_category
                self._metrics.increment_counter(
                    "llm.provider_request",
                    labels=labels,
                )
                self._metrics.observe_latency_ms(
                    "llm.provider_request.duration_ms",
                    (self._clock.monotonic_seconds() - started) * 1000.0,
                    labels={"operation": operation_value, "outcome": outcome},
                )
