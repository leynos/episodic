"""LLM ports and adapter utilities."""

from __future__ import annotations

from .openai_adapter import OpenAICompatibleLLMAdapter, OpenAICompatibleLLMConfig
from .openai_client import (
    OpenAIChatCompletionAdapter,
    OpenAIResponsesAdapter,
    OpenAIResponseValidationError,
    is_openai_chat_completion_payload,
    is_openai_choice_payload,
    is_openai_usage_payload,
)
from .ports import (
    LLMError,
    LLMPort,
    LLMProviderOperation,
    LLMProviderResponseError,
    LLMRequest,
    LLMResponse,
    LLMTokenBudget,
    LLMTokenBudgetExceededError,
    LLMTransientProviderError,
    LLMUsage,
)

__all__: list[str] = [
    "LLMError",
    "LLMPort",
    "LLMProviderOperation",
    "LLMProviderResponseError",
    "LLMRequest",
    "LLMResponse",
    "LLMTokenBudget",
    "LLMTokenBudgetExceededError",
    "LLMTransientProviderError",
    "LLMUsage",
    "OpenAIChatCompletionAdapter",
    "OpenAICompatibleLLMAdapter",
    "OpenAICompatibleLLMConfig",
    "OpenAIResponseValidationError",
    "OpenAIResponsesAdapter",
    "is_openai_chat_completion_payload",
    "is_openai_choice_payload",
    "is_openai_usage_payload",
]
