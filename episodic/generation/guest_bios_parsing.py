"""JSON parsing helpers for guest-bios LLM responses.

This module decodes and validates the JSON payload an LLM returns for guest
biography generation, converting it into :class:`GuestBioEntry` instances and
enforcing that every returned entry cites one of the pinned reference
revisions. It is split out of :mod:`episodic.generation.guest_bios` so that
module stays under the project's line-count limit; import the public names
from :mod:`episodic.generation.guest_bios` rather than from here.
"""

import typing as typ

from episodic.generation.guest_bios_models import GuestBioEntry


class GuestBiosResponseFormatError(ValueError):
    """Raised when the LLM response cannot be parsed into guest biographies."""


def _decode_object(value: object, field_name: str) -> dict[str, object]:
    """Decode a JSON value as an object or raise a format error."""
    if not isinstance(value, dict):
        msg = f"{field_name} must be an object."
        raise GuestBiosResponseFormatError(msg)
    return typ.cast("dict[str, object]", value)


def _require_non_empty_string(value: object, field_name: str) -> str:
    """Require a non-empty string from an LLM payload."""
    if not isinstance(value, str) or value.strip() == "":
        msg = f"{field_name} must be a non-empty string."
        raise GuestBiosResponseFormatError(msg)
    return value


def _require_optional_string(value: object, field_name: str) -> str | None:
    """Return an optional string from an LLM payload."""
    if value is not None and not isinstance(value, str):
        msg = f"{field_name} must be a string or null."
        raise GuestBiosResponseFormatError(msg)
    return value if isinstance(value, str) else None


def _require_list(value: object, field_name: str) -> list[object]:
    """Require a list from an LLM payload."""
    if not isinstance(value, list):
        msg = f"{field_name} must be a list."
        raise GuestBiosResponseFormatError(msg)
    return typ.cast("list[object]", value)


def _parse_entry(raw: dict[str, object]) -> GuestBioEntry:
    """Parse one guest-bio entry from a strict JSON object."""
    display_name = _require_non_empty_string(raw.get("display_name"), "display_name")
    bio = _require_non_empty_string(raw.get("bio"), "bio")
    revision_id = _require_non_empty_string(
        raw.get("reference_document_revision_id"),
        "reference_document_revision_id",
    )
    role = _require_optional_string(raw.get("role"), "role")
    tei_locator = _require_optional_string(raw.get("tei_locator"), "tei_locator")
    try:
        return GuestBioEntry(
            display_name=display_name,
            bio=bio,
            reference_document_revision_id=revision_id,
            role=role,
            tei_locator=tei_locator,
        )
    except ValueError as exc:
        raise GuestBiosResponseFormatError(str(exc)) from exc


def _validate_revision_ids(
    entries: tuple[GuestBioEntry, ...],
    expected_revision_ids: tuple[str, ...],
) -> None:
    """Reject invented, duplicate, or missing guest profile revisions."""
    expected = set(expected_revision_ids)
    seen: set[str] = set()
    for entry in entries:
        revision_id = entry.reference_document_revision_id
        if revision_id not in expected:
            msg = f"unknown revision identifier: {revision_id}"
            raise GuestBiosResponseFormatError(msg)
        if revision_id in seen:
            msg = f"duplicate revision identifier: {revision_id}"
            raise GuestBiosResponseFormatError(msg)
        seen.add(revision_id)
    missing = expected.difference(seen)
    if missing:
        missing_list = ", ".join(sorted(missing))
        msg = f"missing revision identifier: {missing_list}"
        raise GuestBiosResponseFormatError(msg)
