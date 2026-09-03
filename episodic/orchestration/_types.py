"""Domain enums and exceptions for generation orchestration."""

import enum
import json

from episodic.logging import (
    getLogger,
    log_debug,
    log_error,
    log_info,
    log_warning,
)

_log = getLogger(__name__)


def _log_event(level: str, message: str, **fields: object) -> None:
    """Emit one structured log event through the logging port."""
    exc_info = fields.get("exc_info")
    extra_fields = {
        key: value
        for key, value in fields.items()
        if key not in {"exc_info", "stack_info"}
    }
    if extra_fields:
        message = json.dumps({"event": message, **extra_fields}, sort_keys=True)

    match level:
        case "debug":
            log_debug(_log, message, exc_info=exc_info)
        case "info":
            log_info(_log, message, exc_info=exc_info)
        case "warning":
            log_warning(_log, message, exc_info=exc_info)
        case "error":
            log_error(_log, message, exc_info=exc_info)
        case _:
            msg = f"Unsupported orchestration log level: ${level!r}"
            raise ValueError(msg)


class ActionKind(enum.StrEnum):
    """Supported generation-enrichment actions for this orchestration slice."""

    GENERATE_SHOW_NOTES = "generate_show_notes"
    GENERATE_GUEST_BIOS = "generate_guest_bios"


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


class ShowNotesGeneratorNotInitializedError(ToolExecutionError):
    """Raised when the show-notes executor has no initialised generator."""


class ShowNotesFormatError(ToolExecutionError):
    """Raised when the show-notes generator returns malformed structured JSON."""


class GuestBiosFormatError(ToolExecutionError):
    """Raised when the guest-bios generator returns malformed structured JSON."""
