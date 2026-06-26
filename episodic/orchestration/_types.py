"""Domain enums and exceptions for generation orchestration."""

import enum

from episodic.logging import log_event

_log_event = log_event


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


class ShowNotesFormatError(ToolExecutionError):
    """Raised when the show-notes generator returns malformed structured JSON."""


class GuestBiosFormatError(ToolExecutionError):
    """Raised when the guest-bios generator returns malformed structured JSON."""
