"""Map known provider failures to bounded request telemetry outcomes."""

import asyncio

import httpx

from episodic.llm.ports import LLMProviderResponseError, LLMTransientProviderError


def _provider_failure_outcome(
    error: asyncio.CancelledError
    | httpx.TransportError
    | LLMTransientProviderError
    | LLMProviderResponseError,
) -> tuple[str, str]:
    """Classify known provider failures into fixed telemetry labels."""
    match error:
        case asyncio.CancelledError():
            return "cancelled", "provider.cancelled"
        case httpx.TimeoutException():
            return "timeout", "provider.timeout"
        case httpx.TransportError() | LLMTransientProviderError():
            return "retry", "provider.transient"
        case _:
            return "error", "provider.response_invalid"
