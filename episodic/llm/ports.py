"""Port contracts for Large Language Model (LLM) interactions.

This module defines provider-agnostic data transfer objects and the outbound
LLM protocol used by orchestration code.
"""

from __future__ import annotations

import dataclasses as dc
import enum
import typing as typ


class LLMProviderOperation(enum.StrEnum):
    """Supported OpenAI-compatible provider operation shapes."""

    CHAT_COMPLETIONS = "chat_completions"
    RESPONSES = "responses"


@dc.dataclass(frozen=True, slots=True)
class LLMTokenBudget:
    """Token budget constraints enforced around one LLM request."""

    max_input_tokens: int
    max_output_tokens: int
    max_total_tokens: int | None = None

    def __post_init__(self) -> None:
        """Reject negative token budgets at construction time."""
        if self.max_input_tokens < 0:
            msg = "max_input_tokens must be non-negative."
            raise ValueError(msg)
        if self.max_output_tokens < 0:
            msg = "max_output_tokens must be non-negative."
            raise ValueError(msg)
        if self.max_total_tokens is not None and self.max_total_tokens < 0:
            msg = "max_total_tokens must be non-negative."
            raise ValueError(msg)


@dc.dataclass(frozen=True, slots=True)
class LLMUsage:
    """Normalized token usage metadata returned by LLM providers.

    Attributes
    ----------
    input_tokens : int
        Number of prompt/input tokens consumed.
    output_tokens : int
        Number of completion/output tokens consumed.
    total_tokens : int
        Total billable tokens for the request.
    """

    input_tokens: int
    output_tokens: int
    total_tokens: int


@dc.dataclass(frozen=True, slots=True)
class LLMResponse:
    """Normalized LLM response payload.

    Attributes
    ----------
    text : str
        Generated text output.
    model : str
        Provider model identifier used for generation.
    provider_response_id : str
        Provider-native response identifier.
    finish_reason : str | None
        Completion stop reason when provided by the vendor.
    usage : LLMUsage
        Normalized usage metadata used for accounting.
    """

    text: str
    model: str
    provider_response_id: str
    finish_reason: str | None
    usage: LLMUsage


@dc.dataclass(frozen=True, slots=True)
class LLMRequest:
    """Provider-neutral request payload for outbound LLM generation."""

    model: str
    prompt: str
    system_prompt: str | None = None
    provider_operation: LLMProviderOperation | str | None = None
    token_budget: LLMTokenBudget | None = None


class LLMError(Exception):
    """Base exception for LLM port failures."""


class LLMTokenBudgetExceededError(LLMError):
    """Raised when an LLM request exceeds its configured token budget."""


class LLMProviderResponseError(LLMError):
    """Raised when a provider returns a non-retryable error response."""


class LLMTransientProviderError(LLMError):
    """Raised when a provider fails transiently after retries are exhausted."""


@typ.runtime_checkable
class LLMPort(typ.Protocol):
    """Protocol for outbound LLM adapter implementations."""

    async def generate(self, request: LLMRequest) -> LLMResponse:
        """Generate text for a prompt and return usage metadata.

        Parameters
        ----------
        request : LLMRequest
            Provider-neutral generation request, including prompt content,
            optional system guardrails, selected provider operation, and token
            budget metadata.

        Returns
        -------
        LLMResponse
            Normalized provider response and usage details.
        """
        ...
