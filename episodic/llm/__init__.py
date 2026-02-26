"""LLM ports and adapter utilities."""

from __future__ import annotations

from .openai_client import (
    OpenAIChatCompletionAdapter,
    OpenAIChatCompletionPayload,
    OpenAIChoicePayload,
    OpenAIMessagePayload,
    OpenAIResponseValidationError,
    OpenAIUsagePayload,
    is_openai_chat_completion_payload,
    is_openai_choice_payload,
    is_openai_message_payload,
    is_openai_usage_payload,
    normalise_openai_chat_completion,
)
from .ports import LLMPort, LLMResponse, LLMUsage

__all__: list[str] = [
    "LLMPort",
    "LLMResponse",
    "LLMUsage",
    "OpenAIChatCompletionAdapter",
    "OpenAIChatCompletionPayload",
    "OpenAIChoicePayload",
    "OpenAIMessagePayload",
    "OpenAIResponseValidationError",
    "OpenAIUsagePayload",
    "is_openai_chat_completion_payload",
    "is_openai_choice_payload",
    "is_openai_message_payload",
    "is_openai_usage_payload",
    "normalise_openai_chat_completion",
]
