"""Structured error-event logging primitives for the OpenAI adapter.

This module centralizes the log-override context variable, the module
logger, provider-operation label formatting, and structured JSON
error-event emission shared by the OpenAI-compatible adapter's
configuration-validation and budget-enforcement helpers in the sibling
`utils_config`, `utils_preflight`, and `utils_usage` modules.
"""

import contextvars
import json
import typing as typ

from episodic.llm.ports import LLMProviderOperation
from episodic.logging import getLogger

_log = getLogger(__name__)

_log_override: contextvars.ContextVar[typ.Any | None] = contextvars.ContextVar(
    "openai_adapter_log_override", default=None
)


def _operation_label(operation: LLMProviderOperation | str | None) -> str:
    """Return a stable provider-operation label for logs."""
    match operation:
        case None:
            return "default"
        case LLMProviderOperation() as value:
            return value.value
        case str() as value:
            return value
        case _:
            return str(operation)


def _log_error_event(message: str, **fields: object) -> None:
    """Emit one JSON-encoded ERROR event with bounded diagnostic fields."""
    effective_log = _log_override.get() or _log
    effective_log.error(json.dumps({"event": message, **fields}, sort_keys=True))
