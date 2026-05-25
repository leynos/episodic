"""Request construction helpers for OpenAI-compatible LLM operations."""

from episodic.llm.ports import (
    LLMProviderOperation,
    LLMProviderResponseError,
    LLMRequest,
)


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


def _build_payload(
    request: LLMRequest,
    operation: LLMProviderOperation,
) -> dict[str, object]:
    """Build a provider request payload from a provider-neutral request."""
    payload: dict[str, object] = {"model": request.model}
    match operation:
        case LLMProviderOperation.CHAT_COMPLETIONS:
            messages: list[dict[str, str]] = []
            if request.system_prompt is not None:
                messages.append({"role": "system", "content": request.system_prompt})
            messages.append({"role": "user", "content": request.prompt})
            payload["messages"] = messages
            if request.token_budget is not None:
                payload["max_tokens"] = request.token_budget.max_output_tokens
            return payload
        case LLMProviderOperation.RESPONSES:
            payload["input"] = request.prompt
            if request.system_prompt is not None:
                payload["instructions"] = request.system_prompt
            if request.token_budget is not None:
                payload["max_output_tokens"] = request.token_budget.max_output_tokens
            return payload
        case _:
            msg = f"Unsupported provider operation: {operation!r}."
            raise LLMProviderResponseError(msg)
