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
    _require_concrete_usage_counts,
    _validate_llm_config,
    _validate_preflight_budget,
    _validate_usage_budget,
)
from episodic.llm.ports import (
    LLMPort,
    LLMProviderOperation,
    LLMRequest,
    LLMResponse,
    LLMTransientProviderError,
)

if typ.TYPE_CHECKING:
    from types import TracebackType


@dc.dataclass(frozen=True, slots=True)
class OpenAICompatibleLLMConfig:
    """Configuration for the OpenAI-compatible HTTP adapter."""

    base_url: str
    api_key: str
    provider_operation: LLMProviderOperation | str = (
        LLMProviderOperation.CHAT_COMPLETIONS
    )
    max_attempts: int = 3
    retry_delay_seconds: float = 0.5
    timeout_seconds: float = 30.0
    chars_per_token: float = 4.0

    def __post_init__(self) -> None:
        """Validate adapter configuration eagerly."""
        _validate_llm_config(self)


class OpenAICompatibleLLMAdapter(LLMPort):
    """Call an OpenAI-compatible HTTP endpoint using chat or responses shapes."""

    def __init__(
        self,
        *,
        config: OpenAICompatibleLLMConfig,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = config.base_url.rstrip("/")
        self._api_key = config.api_key
        self._provider_operation = _coerce_operation(config.provider_operation)
        self._client = client if client is not None else httpx.AsyncClient()
        self._owns_client = client is None
        self._max_attempts = config.max_attempts
        self._retry_delay_seconds = config.retry_delay_seconds
        self._timeout_seconds = config.timeout_seconds
        self._chars_per_token = config.chars_per_token

    async def __aenter__(self) -> OpenAICompatibleLLMAdapter:
        """Return the adapter for use as an async context manager."""
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
        """Close the adapter-owned HTTP client when present."""
        if self._owns_client:
            await self._client.aclose()

    async def generate(self, request: LLMRequest) -> LLMResponse:
        """Generate text from an OpenAI-compatible provider."""
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
            payload=_build_payload(request, operation),
        )
        if token_budget is not None:
            _require_concrete_usage_counts(response_payload, operation)
        response = _normalize_payload(response_payload, operation)

        if token_budget is not None:
            _validate_usage_budget(response, token_budget, operation)
        return response

    async def _send_with_retries(
        self,
        *,
        path: str,
        payload: dict[str, object],
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
                    return await self._send_once(path=path, payload=payload)
        except RetryError as exc:
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
    ) -> dict[str, object]:
        """Send one provider request and return the decoded JSON payload."""
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
