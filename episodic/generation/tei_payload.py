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


def _format_type_error_message(
    field_name: str,
    expected_type: str,
    prefix: str,
) -> str:
    """Build a consistent type mismatch message for payload validators."""
    qualifier = f"{prefix} " if prefix else ""
    return f"{qualifier}{field_name} must be a {expected_type}."


def require_mapping(
    value: object,
    field_name: str,
    *,
    error_cls: type[Exception],
    prefix: str = "",
) -> dict[str, object]:
    """Require an object value with caller-selected error semantics.

    Parameters
    ----------
    value
        Candidate value to validate.
    field_name
        Field path to include in validation errors.
    error_cls
        Exception type to raise when ``value`` is not a mapping.
    prefix
        Optional message prefix for the field path.

    Returns
    -------
    dict[str, object]
        The validated mapping value.

    Raises
    ------
    Exception
        Instance of ``error_cls`` when ``value`` is not an object.
    """
    if not isinstance(value, dict):
        raise error_cls(_format_type_error_message(field_name, "object", prefix))
    return typ.cast("dict[str, object]", value)


def require_sequence(
    value: object,
    field_name: str,
    *,
    error_cls: type[Exception],
    prefix: str = "",
) -> list[object]:
    """Require a list value with caller-selected error semantics.

    Parameters
    ----------
    value
        Candidate value to validate.
    field_name
        Field path to include in validation errors.
    error_cls
        Exception type to raise when ``value`` is not a list.
    prefix
        Optional message prefix for the field path.

    Returns
    -------
    list[object]
        The validated list value.

    Raises
    ------
    Exception
        Instance of ``error_cls`` when ``value`` is not a list.
    """
    if not isinstance(value, list):
        raise error_cls(_format_type_error_message(field_name, "list", prefix))
    return typ.cast("list[object]", value)


def require_non_empty_str_value(
    value: object,
    field_name: str,
    *,
    error_cls: type[Exception],
    message: str = "must be a non-empty string.",
) -> str:
    """Require a non-empty string value with caller-selected error semantics.

    Parameters
    ----------
    value
        Candidate value to validate.
    field_name
        Field name to include in validation errors.
    error_cls
        Exception type to raise when ``value`` is not a non-empty string.
    message
        Validation message suffix to append after ``field_name``.

    Returns
    -------
    str
        The validated string value.

    Raises
    ------
    Exception
        Instance of ``error_cls`` when ``value`` is not a non-empty string.
    """
    if not isinstance(value, str) or value.strip() == "":
        msg = f"{field_name} {message}"
        raise error_cls(msg)
    return value


def require_payload_object(value: object, field_name: str) -> dict[str, object]:
    """Require a mapping inside a TEI payload.

    Parameters
    ----------
    value
        Candidate TEI payload field value.
    field_name
        TEI payload field path to include in validation errors.

    Returns
    -------
    dict[str, object]
        The validated TEI payload mapping.

    Raises
    ------
    ValueError
        If ``value`` is not an object.
    """
    return require_mapping(
        value,
        field_name,
        error_cls=ValueError,
        prefix="TEI payload field",
    )


def require_payload_list(value: object, field_name: str) -> list[object]:
    """Require a list inside a TEI payload.

    Parameters
    ----------
    value
        Candidate TEI payload field value.
    field_name
        TEI payload field path to include in validation errors.

    Returns
    -------
    list[object]
        The validated TEI payload list.

    Raises
    ------
    ValueError
        If ``value`` is not a list.
    """
    return require_sequence(
        value,
        field_name,
        error_cls=ValueError,
        prefix="TEI payload field",
    )


def body_blocks_payload(document_payload: dict[str, object]) -> list[object]:
    """Return the mutable TEI body blocks list from a document payload.

    Parameters
    ----------
    document_payload
        ``tei_rapporteur`` document payload containing ``text.body.blocks``.

    Returns
    -------
    list[object]
        Mutable reference to the document's body blocks list; callers may
        mutate this list to update the emitted TEI body.

    Raises
    ------
    ValueError
        If ``text``, ``text.body``, or ``text.body.blocks`` has the wrong
        payload shape.
    """
    text_payload = require_payload_object(document_payload.get("text"), "text")
    body_payload = require_payload_object(text_payload.get("body"), "text.body")
    return require_payload_list(body_payload.get("blocks"), "text.body.blocks")


def is_div_payload(value: object, div_type: str) -> bool:
    """Return whether a body block is a TEI div payload of ``div_type``.

    Parameters
    ----------
    value
        Candidate body block payload.
    div_type
        Expected typed div value from the ``div_type`` field.

    Returns
    -------
    bool
        ``True`` when ``value`` is a div payload with the requested type.

    Raises
    ------
    None
        This helper does not raise for malformed payloads.
    """
    if not isinstance(value, dict):
        return False
    payload = typ.cast("dict[str, object]", value)
    return payload.get("type") == "div" and payload.get("div_type") == div_type


def build_text_inline(text: str) -> list[dict[str, str]]:
    """Build a plain-text inline payload for ``tei_rapporteur``.

    Parameters
    ----------
    text
        Plain text value to wrap as an inline text node.

    Returns
    -------
    list[dict[str, str]]
        Inline payload containing one text node.

    Raises
    ------
    None
        This helper performs no validation and does not raise.
    """
    return [{"type": "text", "value": text}]
