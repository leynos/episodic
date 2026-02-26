"""Port contracts for large language model interactions.

This module defines provider-agnostic data transfer objects and the outbound
LLM protocol used by orchestration code.
"""

from __future__ import annotations

import dataclasses as dc
import typing as typ


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


class LLMPort(typ.Protocol):
    """Protocol for outbound LLM adapter implementations."""

    async def generate(self, prompt: str) -> LLMResponse:
        """Generate text for a prompt and return usage metadata.

        Parameters
        ----------
        prompt : str
            Prompt content submitted to the provider.

        Returns
        -------
        LLMResponse
            Normalized provider response and usage details.
        """
        ...
