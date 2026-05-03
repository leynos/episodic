"""Domain enums and exceptions for generation orchestration."""

import enum
import json

from episodic.logging import getLogger

_log = getLogger(__name__)


def _log_event(level: str, message: str, **fields: object) -> None:
    """Emit one structured log event with a JSON fallback."""
    log_method = getattr(_log, level)
    try:
        log_method(message, **fields)
    except TypeError:
        payload = {"event": message, **fields}
        log_method(json.dumps(payload, sort_keys=True))


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
