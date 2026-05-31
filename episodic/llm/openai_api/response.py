"""Response decoding and normalization for OpenAI-compatible providers.

The adapter receives raw `httpx.Response` objects and provider-specific JSON
payloads, while the rest of the LLM boundary works with provider-neutral
`LLMResponse` values. This module keeps that translation isolated from
transport orchestration in `adapter` and request construction in `request`.

HTTP status checks classify retryable provider failures before JSON decoding.
Decoded payloads are then delegated to the existing OpenAI response adapters in
`openai_client`, preserving one normalization path for chat completions and
Responses API payloads.
"""

import json
import typing as typ

from episodic.llm.openai_client import (
    OpenAIChatCompletionAdapter,
    OpenAIResponsesAdapter,
    OpenAIResponseValidationError,
)
from episodic.llm.ports import (
    LLMProviderOperation,
    LLMProviderResponseError,
    LLMResponse,
    LLMTransientProviderError,
)

if typ.TYPE_CHECKING:
    import httpx

_RETRYABLE_STATUS_CODES = frozenset({429, 500, 502, 503, 504})
_HTTP_REDIRECT_THRESHOLD = 300
_HTTP_BAD_REQUEST_THRESHOLD = 400


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
    if (
        response.status_code >= _HTTP_REDIRECT_THRESHOLD
        and response.status_code < _HTTP_BAD_REQUEST_THRESHOLD
    ):
        msg = (
            "Provider returned an unexpected redirect response: "
            f"{response.status_code}."
        )
        raise LLMProviderResponseError(msg)
    if response.status_code >= _HTTP_BAD_REQUEST_THRESHOLD:
        msg = (
            f"Provider returned a non-retryable error response: {response.status_code}."
        )
        raise LLMProviderResponseError(msg)


def _decode_json_response(  # pylint: disable=no-else-raise  # keep decode and shape-validation paths visibly separated
    response: httpx.Response,
) -> dict[str, object]:
    """Decode and validate the JSON body of a provider response."""
    try:
        payload = response.json()
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        msg = "Provider returned malformed JSON."
        raise LLMProviderResponseError(msg) from exc
    else:
        if not isinstance(payload, dict):
            msg = "Provider returned a non-object JSON payload."
            raise LLMProviderResponseError(msg)
        return typ.cast("dict[str, object]", payload)
