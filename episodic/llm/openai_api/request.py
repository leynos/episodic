"""Build OpenAI-compatible provider request payloads.

This module converts provider-neutral ``LLMRequest`` values into the endpoint
paths and JSON payload shapes expected by OpenAI-compatible chat-completions and
Responses API providers. ``OpenAICompatibleLLMAdapter`` imports these helpers to
keep transport retry logic separate from operation-specific request assembly.

Callers normally use the public adapter facade rather than importing this
module directly. Internal adapter code calls ``_coerce_operation()`` to
normalise operation names, ``_path_for_operation()`` to select the provider
route, and ``_build_payload()`` to build the request body.

Examples
--------
Build a chat-completions payload:

>>> from episodic.llm.ports import LLMProviderOperation, LLMRequest
>>> request = LLMRequest(model="gpt-4o-mini", prompt="Draft an intro.")
>>> _path_for_operation(LLMProviderOperation.CHAT_COMPLETIONS)
'/chat/completions'
>>> payload = _build_payload(request, LLMProviderOperation.CHAT_COMPLETIONS)
>>> payload["messages"][0]["role"]
'user'

Build a Responses API payload:

>>> payload = _build_payload(request, LLMProviderOperation.RESPONSES)
>>> payload["input"]
'Draft an intro.'
"""

import dataclasses as dc

from episodic.llm.ports import (
    LLMProviderOperation,
    LLMProviderResponseError,
    LLMRequest,
)

_TOKEN_LIMIT_PARAMS = frozenset({"max_tokens", "max_completion_tokens"})


@dc.dataclass(frozen=True, slots=True)
class OpenAIPayloadOptions:
    """Provider-specific request options applied to outbound payloads.

    Attributes
    ----------
    reasoning_effort : str | None
        Reasoning effort hint for reasoning-capable models (for example,
        ``"low"``). Omitted from the payload when ``None``.
    service_tier : str | None
        Provider service tier (for example, ``"flex"``). Omitted from the
        payload when ``None``.
    token_limit_param : str
        Chat-completions parameter name that carries the output token cap.
        Reasoning models require ``"max_completion_tokens"``; older
        OpenAI-compatible providers expect ``"max_tokens"``.
    """

    reasoning_effort: str | None = None
    service_tier: str | None = None
    token_limit_param: str = "max_tokens"  # noqa: S105 - parameter name, not a secret.

    def __post_init__(self) -> None:
        """Reject unsupported token-limit parameter names."""
        if self.token_limit_param not in _TOKEN_LIMIT_PARAMS:
            msg = (
                "token_limit_param must be one of "
                f"{sorted(_TOKEN_LIMIT_PARAMS)}; got {self.token_limit_param!r}."
            )
            raise ValueError(msg)


def _coerce_operation(value: LLMProviderOperation | str) -> LLMProviderOperation:
    """Normalize a provider operation enum value."""
    if isinstance(value, LLMProviderOperation):
        return value
    try:
        return LLMProviderOperation(value)
    except ValueError as exc:
        msg = f"Unsupported provider operation: {value!r}."
        raise LLMProviderResponseError(msg) from exc


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


def _apply_chat_options(
    payload: dict[str, object],
    request: LLMRequest,
    opts: OpenAIPayloadOptions,
) -> None:
    """Apply chat-completions request options to a payload."""
    if request.token_budget is not None:
        payload[opts.token_limit_param] = request.token_budget.max_output_tokens
    if request.json_response:
        payload["response_format"] = {"type": "json_object"}
    if opts.reasoning_effort is not None:
        payload["reasoning_effort"] = opts.reasoning_effort


def _apply_responses_options(
    payload: dict[str, object],
    request: LLMRequest,
    opts: OpenAIPayloadOptions,
) -> None:
    """Apply Responses API request options to a payload."""
    if request.token_budget is not None:
        payload["max_output_tokens"] = request.token_budget.max_output_tokens
    if request.json_response:
        payload["text"] = {"format": {"type": "json_object"}}
    if opts.reasoning_effort is not None:
        payload["reasoning"] = {"effort": opts.reasoning_effort}


def _build_payload(
    request: LLMRequest,
    operation: LLMProviderOperation,
    *,
    options: OpenAIPayloadOptions | None = None,
) -> dict[str, object]:
    """Build a provider request payload from a provider-neutral request."""
    opts = options if options is not None else OpenAIPayloadOptions()
    payload: dict[str, object] = {"model": request.model}
    if opts.service_tier is not None:
        payload["service_tier"] = opts.service_tier
    match operation:
        case LLMProviderOperation.CHAT_COMPLETIONS:
            messages: list[dict[str, str]] = []
            if request.system_prompt is not None:
                messages.append({"role": "system", "content": request.system_prompt})
            messages.append({"role": "user", "content": request.prompt})
            payload["messages"] = messages
            _apply_chat_options(payload, request, opts)
            return payload
        case LLMProviderOperation.RESPONSES:
            payload["input"] = request.prompt
            if request.system_prompt is not None:
                payload["instructions"] = request.system_prompt
            _apply_responses_options(payload, request, opts)
            return payload
        case _:
            msg = f"Unsupported provider operation: {operation!r}."
            raise LLMProviderResponseError(msg)
