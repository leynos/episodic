"""Shared helpers for TEI payload enrichment modules.

Use these utilities when an enrichment module needs to inspect or mutate the
`tei_rapporteur` dictionary payload produced from a TEI document. The helpers
validate mapping and list shapes, locate mutable body blocks, identify typed
`div` payloads, and build plain-text inline payloads consistently across
enrichment features.

Example:
    payload = {"text": {"body": {"blocks": []}}}
    blocks = body_blocks_payload(payload)
    blocks.append({
        "type": "div",
        "div_type": "notes",
        "content": build_text_inline("Notes"),
    })
"""

import typing as typ


def require_mapping(
    value: object,
    field_name: str,
    *,
    error_cls: type[Exception],
    prefix: str = "",
) -> dict[str, object]:
    """Require an object value with caller-selected error semantics."""
    if not isinstance(value, dict):
        qualifier = f"{prefix} " if prefix else ""
        msg = f"{qualifier}{field_name} must be an object."
        raise error_cls(msg)
    return typ.cast("dict[str, object]", value)


def require_sequence(
    value: object,
    field_name: str,
    *,
    error_cls: type[Exception],
    prefix: str = "",
) -> list[object]:
    """Require a list value with caller-selected error semantics."""
    if not isinstance(value, list):
        qualifier = f"{prefix} " if prefix else ""
        msg = f"{qualifier}{field_name} must be a list."
        raise error_cls(msg)
    return typ.cast("list[object]", value)


def require_non_empty_str_value(
    value: object,
    field_name: str,
    *,
    error_cls: type[Exception],
    message: str = "must be a non-empty string.",
) -> str:
    """Require a non-empty string value with caller-selected error semantics."""
    if not isinstance(value, str) or value.strip() == "":
        msg = f"{field_name} {message}"
        raise error_cls(msg)
    return value


def require_payload_object(value: object, field_name: str) -> dict[str, object]:
    """Require a mapping inside a TEI payload or raise ValueError."""
    return require_mapping(
        value,
        field_name,
        error_cls=ValueError,
        prefix="TEI payload field",
    )


def require_payload_list(value: object, field_name: str) -> list[object]:
    """Require a list inside a TEI payload or raise ValueError."""
    return require_sequence(
        value,
        field_name,
        error_cls=ValueError,
        prefix="TEI payload field",
    )


def body_blocks_payload(document_payload: dict[str, object]) -> list[object]:
    """Return the mutable TEI body blocks list from a document payload."""
    text_payload = require_payload_object(document_payload.get("text"), "text")
    body_payload = require_payload_object(text_payload.get("body"), "text.body")
    return require_payload_list(body_payload.get("blocks"), "text.body.blocks")


def is_div_payload(value: object, div_type: str) -> bool:
    """Return True when a body block is a TEI div payload of *div_type*."""
    if not isinstance(value, dict):
        return False
    payload = typ.cast("dict[str, object]", value)
    return payload.get("type") == "div" and payload.get("div_type") == div_type


def build_text_inline(text: str) -> list[dict[str, str]]:
    """Build a plain-text inline payload for tei_rapporteur."""
    return [{"type": "text", "value": text}]
