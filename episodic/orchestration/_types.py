"""Domain enums and exceptions for generation orchestration."""

import enum
import json

from episodic.logging import getLogger

_log = getLogger(__name__)


def _log_event(level: str, message: str, **fields: object) -> None:
    """Emit one structured log event with a JSON fallback.

    Logger convenience methods (``debug``, ``info``, ...) only accept
    ``exc_info`` / ``stack_info`` besides the message. Structured fields are
    serialized into one JSON message when needed.
    """
    log_method = getattr(_log, level)
    allowed_kwargs = {
        k: v for k, v in fields.items() if k in {"exc_info", "stack_info"}
    }
    extra_fields = {k: v for k, v in fields.items() if k not in allowed_kwargs}
    if extra_fields:
        payload = {"event": message, **extra_fields}
        log_method(json.dumps(payload, sort_keys=True), **allowed_kwargs)
        return
    try:
        log_method(message, **allowed_kwargs)
    except TypeError:
        payload = {"event": message}
        log_method(json.dumps(payload, sort_keys=True), **allowed_kwargs)


class ActionKind(enum.StrEnum):
    """Supported generation-enrichment actions for this orchestration slice."""

    GENERATE_SHOW_NOTES = "generate_show_notes"


class ModelTier(enum.StrEnum):
    """Logical model tiers used by the orchestration planner and executor."""

    PLANNING = "planning"
    EXECUTION = "execution"


class PlanningResponseFormatError(ValueError):
    """Raised when the planner returns malformed structured output."""


class UnsupportedActionError(ValueError):
    """Raised when a tool executor receives an unsupported action."""


class ToolExecutionError(RuntimeError):
    """Raised when a planned action fails during tool execution."""


class ShowNotesFormatError(ToolExecutionError):
    """Raised when the show-notes generator returns malformed structured JSON."""
