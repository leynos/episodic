"""Concrete OpenAI-compatible async LLM adapter."""

from __future__ import annotations

import asyncio
import dataclasses as dc
import json
import math
import typing as typ

import httpx

from episodic.llm.openai_client import (
    OpenAIChatCompletionAdapter,
    OpenAIResponsesAdapter,
    OpenAIResponseValidationError,
)
from episodic.llm.ports import (
    LLMPort,
    LLMProviderOperation,
    LLMProviderResponseError,
    LLMRequest,
    LLMResponse,
    LLMTokenBudget,
    LLMTokenBudgetExceededError,
    LLMTransientProviderError,
)

if typ.TYPE_CHECKING:
    from types import TracebackType

_RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
_HTTP_BAD_REQUEST_THRESHOLD = 400


def _estimate_token_count(*parts: str | None) -> int:
    """Estimate prompt tokens using a conservative ~4 chars/token heuristic.

    This heuristic approximates OpenAI/tiktoken GPT-4-era tokenization by
    returning ``ceil(len(text) / 4)`` for the combined non-``None`` prompt
    parts. Actual token counts vary by text shape, language, and vocabulary,
    so this remains a heuristic-only implementation. If other tokenizers need
    support later, this function is the extension point for injecting a
    tokenizer or configurable chars-per-token ratio.
    """
    combined = "".join(part for part in parts if part is not None)
    if combined == "":
        return 0
    return math.ceil(len(combined) / 4)


def _coerce_operation(value: LLMProviderOperation | str) -> LLMProviderOperation:
    """Normalize a provider operation enum value."""
    if isinstance(value, LLMProviderOperation):
        return value
    try:
        return LLMProviderOperation(value)
    except ValueError as exc:
        msg = f"Unsupported provider operation: {value!r}."
        raise LLMProviderResponseError(msg) from exc


def _validate_preflight_budget(
    request: LLMRequest,
    token_budget: LLMTokenBudget,
) -> None:
    """Reject requests that obviously cannot fit within the configured budget."""
    estimated_input_tokens = _estimate_token_count(
        request.system_prompt, request.prompt
    )
    if estimated_input_tokens > token_budget.max_input_tokens:
        msg = (
            "Estimated input token budget exceeded: "
            f"{estimated_input_tokens} > {token_budget.max_input_tokens}."
        )
        raise LLMTokenBudgetExceededError(msg)
    if token_budget.max_total_tokens is not None:
        projected_total = estimated_input_tokens + token_budget.max_output_tokens
        if projected_total > token_budget.max_total_tokens:
            msg = (
                "Estimated total token budget exceeded: "
                f"{projected_total} > {token_budget.max_total_tokens}."
            )
            raise LLMTokenBudgetExceededError(msg)


def _validate_usage_budget(response: LLMResponse, token_budget: LLMTokenBudget) -> None:
    """Reject responses whose actual usage exceeds the configured budget."""
    if response.usage.input_tokens > token_budget.max_input_tokens:
        msg = (
            "Provider usage exceeded input token budget: "
            f"{response.usage.input_tokens} > {token_budget.max_input_tokens}."
        )
        raise LLMTokenBudgetExceededError(msg)
    if response.usage.output_tokens > token_budget.max_output_tokens:
        msg = (
            "Provider usage exceeded output token budget: "
            f"{response.usage.output_tokens} > {token_budget.max_output_tokens}."
        )
        raise LLMTokenBudgetExceededError(msg)
    if (
        token_budget.max_total_tokens is not None
        and response.usage.total_tokens > token_budget.max_total_tokens
    ):
        msg = (
            "Provider usage exceeded total token budget: "
            f"{response.usage.total_tokens} > {token_budget.max_total_tokens}."
        )
        raise LLMTokenBudgetExceededError(msg)


def _has_non_negative_int_mapping_value(
    payload: dict[str, object],
    field_name: str,
) -> bool:
    """Check whether a mapping field contains a non-negative integer."""
    value = payload.get(field_name)
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _require_concrete_usage_counts(
    payload: dict[str, object],
    operation: LLMProviderOperation,
) -> None:
    """Require concrete input/output usage counts for budget enforcement."""
    usage = payload.get("usage")
    if not isinstance(usage, dict):
        msg = "Provider response omitted concrete usage counts required for budgets."
        raise LLMProviderResponseError(msg)
    usage_mapping = typ.cast("dict[str, object]", usage)

    required_fields = (
        ("prompt_tokens", "completion_tokens")
        if operation is LLMProviderOperation.CHAT_COMPLETIONS
        else ("input_tokens", "output_tokens")
    )
    if not all(
        _has_non_negative_int_mapping_value(usage_mapping, field)
        for field in required_fields
    ):
        msg = "Provider response usage must include concrete input/output token counts."
        raise LLMProviderResponseError(msg)


def _path_for_operation(operation: LLMProviderOperation) -> str:
    """Return the provider path for one operation shape."""
    match operation:
        case LLMProviderOperation.CHAT_COMPLETIONS:
            return "/chat/completions"
        case LLMProviderOperation.RESPONSES:
            return "/responses"
        case _:
            msg = f"Unsupported provider operation: {operation!r}."
            raise LLMProviderResponseError(msg)


def _build_payload(
    request: LLMRequest,
    operation: LLMProviderOperation,
) -> dict[str, object]:
    """Build a provider request payload from a provider-neutral request."""
    payload: dict[str, object] = {"model": request.model}
    if operation is LLMProviderOperation.CHAT_COMPLETIONS:
        messages: list[dict[str, str]] = []
        if request.system_prompt is not None:
            messages.append({"role": "system", "content": request.system_prompt})
        messages.append({"role": "user", "content": request.prompt})
        payload["messages"] = messages
        if request.token_budget is not None:
            payload["max_tokens"] = request.token_budget.max_output_tokens
        return payload

    payload["input"] = request.prompt
    if request.system_prompt is not None:
        payload["instructions"] = request.system_prompt
    if request.token_budget is not None:
        payload["max_output_tokens"] = request.token_budget.max_output_tokens
    return payload


def _normalize_payload(
    payload: dict[str, object],
    operation: LLMProviderOperation,
) -> LLMResponse:
    """Normalize a provider payload into the domain response DTO."""
    try:
        match operation:
            case LLMProviderOperation.CHAT_COMPLETIONS:
                return OpenAIChatCompletionAdapter.normalize_chat_completion(payload)
            case LLMProviderOperation.RESPONSES:
                return OpenAIResponsesAdapter.normalize_response(payload)
            case _:
                msg = f"Unsupported provider operation: {operation!r}."
                raise LLMProviderResponseError(msg)
    except OpenAIResponseValidationError as exc:
        msg = "Provider returned an invalid OpenAI-compatible response payload."
        raise LLMProviderResponseError(msg) from exc


def _check_http_status(response: httpx.Response) -> None:
    """Raise appropriate errors for non-2xx HTTP responses."""
    if response.status_code in _RETRYABLE_STATUS_CODES:
        msg = f"Transient provider HTTP status {response.status_code}."
        raise LLMTransientProviderError(msg)
    if response.status_code >= _HTTP_BAD_REQUEST_THRESHOLD:
        msg = (
            f"Provider returned a non-retryable error response: {response.status_code}."
        )
        raise LLMProviderResponseError(msg)


def _decode_json_response(response: httpx.Response) -> dict[str, object]:
    """Decode and validate the JSON body of a provider response."""
    try:
        payload = response.json()
    except json.JSONDecodeError as exc:
        msg = "Provider returned malformed JSON."
        raise LLMProviderResponseError(msg) from exc
    if not isinstance(payload, dict):
        msg = "Provider returned a non-object JSON payload."
        raise LLMProviderResponseError(msg)
    return typ.cast("dict[str, object]", payload)


def _validate_llm_config(  # noqa: PLR0913
    *,
    max_attempts: int,
    retry_delay_seconds: float,
    timeout_seconds: float,
    base_url: str,
    api_key: str,
) -> None:
    """Validate OpenAICompatibleLLMConfig field values."""
    if max_attempts <= 0:
        msg = "max_attempts must be greater than zero."
        raise ValueError(msg)
    if retry_delay_seconds < 0:
        msg = "retry_delay_seconds must be non-negative."
        raise ValueError(msg)
    if timeout_seconds <= 0:
        msg = "timeout_seconds must be greater than zero."
        raise ValueError(msg)
    if not base_url.strip():
        msg = "base_url must be non-empty."
        raise ValueError(msg)
    if not api_key.strip():
        msg = "api_key must be non-empty."
        raise ValueError(msg)


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

    def __post_init__(self) -> None:
        """Validate adapter configuration eagerly."""
        _validate_llm_config(
            max_attempts=self.max_attempts,
            retry_delay_seconds=self.retry_delay_seconds,
            timeout_seconds=self.timeout_seconds,
            base_url=self.base_url,
            api_key=self.api_key,
        )


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
            _validate_preflight_budget(request, token_budget)

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
            _validate_usage_budget(response, token_budget)
        return response

    async def _send_with_retries(
        self,
        *,
        path: str,
        payload: dict[str, object],
    ) -> dict[str, object]:
        """Send a provider request with retry handling for transient failures."""
        last_exception: Exception | None = None
        for attempt in range(1, self._max_attempts + 1):
            try:
                return await self._send_once(path=path, payload=payload)
            except (httpx.TransportError, LLMTransientProviderError) as exc:
                last_exception = exc
                if attempt >= self._max_attempts:
                    break
                await asyncio.sleep(self._retry_delay_seconds)

        msg = "Transient provider failure after exhausting retries."
        raise LLMTransientProviderError(msg) from last_exception

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
