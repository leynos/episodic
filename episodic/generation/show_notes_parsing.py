"""JSON parsing helpers for show-notes LLM responses.

This module decodes and validates the JSON payload an LLM returns for
show-notes extraction, converting it into :class:`ShowNotesEntry` instances.
It is split out of :mod:`episodic.generation.show_notes` so that module stays
under the project's line-count limit; import the public names from
:mod:`episodic.generation.show_notes` rather than from here.
"""

from episodic.generation.show_notes_models import ShowNotesEntry
from episodic.generation.tei_payload import (
    require_mapping,
    require_non_empty_str_value,
    require_sequence,
)


class ShowNotesResponseFormatError(ValueError):
    """Raised when the LLM response cannot be parsed into ShowNotesResult."""


def _decode_object(value: object, field_name: str) -> dict[str, object]:
    """Decode a JSON value as a dictionary or raise a format error."""
    return require_mapping(
        value,
        field_name,
        error_cls=ShowNotesResponseFormatError,
    )


def _require_non_empty_string(value: object, field_name: str) -> str:
    """Require a non-empty string value or raise a format error."""
    return require_non_empty_str_value(
        value,
        field_name,
        error_cls=ShowNotesResponseFormatError,
    )


def _require_optional_string(value: object, field_name: str) -> str | None:
    """Return an input string unchanged or ``None``.

    Returns
    -------
    str | None
        The input string unchanged, or ``None`` when the input is ``None``.

    Raises
    ------
    ShowNotesResponseFormatError
        If *value* is neither a string nor ``None``.
    """
    if value is not None and not isinstance(value, str):
        msg = f"{field_name} must be a string or null."
        raise ShowNotesResponseFormatError(msg)
    return value if isinstance(value, str) else None


def _require_list(value: object, field_name: str) -> list[object]:
    """Require a list value or raise a format error."""
    return require_sequence(
        value,
        field_name,
        error_cls=ShowNotesResponseFormatError,
    )


def _parse_entry(raw: dict[str, object]) -> ShowNotesEntry:
    """Parse a single show-notes entry from a JSON payload."""
    topic = _require_non_empty_string(raw.get("topic"), "topic")
    summary = _require_non_empty_string(raw.get("summary"), "summary")
    timestamp = _require_optional_string(raw.get("timestamp"), "timestamp")
    tei_locator = _require_optional_string(raw.get("tei_locator"), "tei_locator")
    try:
        return ShowNotesEntry(
            topic=topic,
            summary=summary,
            timestamp=timestamp,
            tei_locator=tei_locator,
        )
    except ValueError as exc:
        raise ShowNotesResponseFormatError(str(exc)) from exc
