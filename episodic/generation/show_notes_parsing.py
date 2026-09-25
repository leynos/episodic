"""Parse provider payloads into validated show-notes results."""

import json
import typing as typ

from episodic.generation.show_notes import (
    ShowNotesEntry,
    ShowNotesResponseFormatError,
    ShowNotesResult,
)
from episodic.generation.tei_payload import (
    require_mapping,
    require_non_empty_str_value,
    require_sequence,
)

if typ.TYPE_CHECKING:
    from episodic.llm import LLMResponse


def parse_show_notes_response(response: LLMResponse) -> ShowNotesResult:
    """Parse an LLM response into a validated show-notes result."""
    try:
        payload = json.loads(response.text)
    except json.JSONDecodeError as exc:
        msg = "LLM response is not valid JSON."
        raise ShowNotesResponseFormatError(msg) from exc

    payload_dict = require_mapping(
        payload,
        "response",
        error_cls=ShowNotesResponseFormatError,
    )
    entries_raw = require_sequence(
        payload_dict.get("entries"),
        "entries",
        error_cls=ShowNotesResponseFormatError,
    )
    entries = tuple(
        _parse_entry(_decode_object(entry, "entry")) for entry in entries_raw
    )
    return ShowNotesResult(
        entries=entries,
        usage=response.usage,
        model=response.model,
        provider_response_id=response.provider_response_id,
        finish_reason=response.finish_reason,
        provider_call_usage=response.provider_call_usage,
    )


def _decode_object(value: object, field_name: str) -> dict[str, object]:
    """Decode a JSON value as a dictionary or raise a format error."""
    return require_mapping(value, field_name, error_cls=ShowNotesResponseFormatError)


def _parse_entry(raw: dict[str, object]) -> ShowNotesEntry:
    """Parse one show-notes entry from a JSON payload."""
    topic = require_non_empty_str_value(
        raw.get("topic"), "topic", error_cls=ShowNotesResponseFormatError
    )
    summary = require_non_empty_str_value(
        raw.get("summary"), "summary", error_cls=ShowNotesResponseFormatError
    )
    try:
        return ShowNotesEntry(
            topic=topic,
            summary=summary,
            timestamp=_optional_string(raw.get("timestamp"), "timestamp"),
            tei_locator=_optional_string(raw.get("tei_locator"), "tei_locator"),
        )
    except ValueError as exc:
        raise ShowNotesResponseFormatError(str(exc)) from exc


def _optional_string(value: object, field_name: str) -> str | None:
    """Return a string or null payload field, rejecting other JSON values."""
    if value is not None and not isinstance(value, str):
        msg = f"{field_name} must be a string or null."
        raise ShowNotesResponseFormatError(msg)
    return value if isinstance(value, str) else None
