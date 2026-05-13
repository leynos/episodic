"""Compatibility re-exports for OpenAI adapter payload validation.

Provider payload parsing is intentionally centralized at the adapter boundary.
The implementation lives in focused chat, Responses, and shared validation
modules while this façade preserves the original import surface.
"""

from .openai_chat import (
    OpenAIChatCompletionAdapter,
    is_openai_chat_completion_payload,
    is_openai_choice_payload,
)
from .openai_responses import OpenAIResponsesAdapter
from .openai_validation import (
    OpenAIResponseValidationError,
    is_openai_usage_payload,
)

__all__ = (
    "OpenAIChatCompletionAdapter",
    "OpenAIResponseValidationError",
    "OpenAIResponsesAdapter",
    "is_openai_chat_completion_payload",
    "is_openai_choice_payload",
    "is_openai_usage_payload",
)
