"""Shared helpers for TEI payload enrichment modules."""

import typing as typ


def require_payload_object(value: object, field_name: str) -> dict[str, object]:
    """Require a mapping inside a TEI payload or raise ValueError."""
    if not isinstance(value, dict):
        msg = f"TEI payload field {field_name} must be an object."
        raise ValueError(msg)  # noqa: TRY004
    return typ.cast("dict[str, object]", value)


def require_payload_list(value: object, field_name: str) -> list[object]:
    """Require a list inside a TEI payload or raise ValueError."""
    if not isinstance(value, list):
        msg = f"TEI payload field {field_name} must be a list."
        raise ValueError(msg)  # noqa: TRY004
    return typ.cast("list[object]", value)


def build_text_inline(text: str) -> list[dict[str, str]]:
    """Build a plain-text inline payload for tei_rapporteur."""
    return [{"type": "text", "value": text}]
