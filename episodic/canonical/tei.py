"""TEI parsing helpers built on tei-rapporteur.

This module wraps tei-rapporteur to validate TEI payloads and extract the
canonical header metadata used in ingestion services. It provides a consistent
typed surface around the parser and standardized error messages for missing
header data.

Examples
--------
Parse a TEI header payload from XML:

>>> payload = parse_tei_header("<TEI>...</TEI>")
>>> payload.title
'Example'
"""

from __future__ import annotations

import collections.abc as cabc
import dataclasses as dc
import typing as typ

import tei_rapporteur as _tei

type TEIPayload = dict[str, object]
type ParseXmlFn = cabc.Callable[[str], object]
type ToDictFn = cabc.Callable[[object], object]

_MISSING_HEADER_MESSAGE = "XML processing error: missing field `teiHeader`"
_MISSING_TITLE_MESSAGE = "XML processing error: missing field `title`"


def _default_parse_xml(xml: str) -> object:
    """Parse XML using the default tei_rapporteur binding."""
    return _tei.parse_xml(xml)


def _default_to_dict(document: object) -> object:
    """Serialize a parsed TEI document using the default binding."""
    if not isinstance(document, _tei.Document):
        msg = "TEI parser returned unexpected document type."
        raise TypeError(msg)
    return _tei.to_dict(document)


@dc.dataclass(frozen=True, slots=True)
class TeiHeaderPayload:
    """Parsed TEI header payload and derived metadata.

    Attributes
    ----------
    title : str
        Parsed title extracted from the TEI header.
    payload : TEIPayload
        Header dictionary extracted from the parsed TEI document.
    """

    title: str
    payload: TEIPayload


def _parse_and_validate_tei(
    xml: str,
    parse_xml: ParseXmlFn = _default_parse_xml,
) -> object:
    """Parse TEI XML and validate the document."""
    try:
        document = parse_xml(xml)
        validate = getattr(document, "validate", None)
        if not callable(validate):
            msg = "TEI parser returned document without callable validate()."
            raise TypeError(msg)
        validate()
    except ValueError as exc:
        message = str(exc)
        if message == _MISSING_HEADER_MESSAGE:
            msg = "TEI header missing from parsed payload."
            raise TypeError(msg) from exc
        if message == _MISSING_TITLE_MESSAGE:
            msg = "TEI header title missing from parsed payload."
            raise ValueError(msg) from exc
        raise
    return document


def _to_payload(
    document: object,
    to_dict: ToDictFn = _default_to_dict,
) -> TEIPayload:
    """Convert a parsed TEI document into a string-keyed payload."""
    payload = to_dict(document)
    if not isinstance(payload, dict):
        msg = "TEI parser produced non-mapping payload."
        raise TypeError(msg)

    typed_payload: TEIPayload = {}
    for key, value in payload.items():
        if not isinstance(key, str):
            msg = "TEI parser produced non-string payload keys."
            raise TypeError(msg)
        typed_payload[key] = value
    return typed_payload


def _extract_header(payload: TEIPayload) -> TEIPayload:
    """Extract the TEI header from a parsed payload."""
    header = payload.get("teiHeader") or payload.get("header")
    match header:
        case dict() as header_dict:
            return typ.cast("TEIPayload", header_dict)
        case _:
            msg = "TEI header missing from parsed payload."
            raise TypeError(msg)


def _extract_title(header: TEIPayload) -> str:
    """Extract the TEI header title."""
    file_desc = typ.cast(
        "TEIPayload",
        header.get("fileDesc") or header.get("file_desc") or {},
    )
    title = file_desc.get("title")
    match title:
        case str() as title_value if title_value.strip():
            return title_value
        case _:
            msg = "TEI header title missing from parsed payload."
            raise ValueError(msg)


def parse_tei_header(xml: str) -> TeiHeaderPayload:
    """Parse a TEI XML payload and extract the header.

    Parameters
    ----------
    xml : str
        TEI XML payload to parse.

    Returns
    -------
    TeiHeaderPayload
        Parsed TEI header payload and derived metadata.

    Raises
    ------
    TypeError
        If the TEI header is missing from the parsed payload.
    ValueError
        If the TEI header title is missing or empty.
    ValueError
        If the TEI parser raises a validation error that does not map to a
        missing header or title.
    """
    document = _parse_and_validate_tei(xml)
    payload = _to_payload(document)
    header = _extract_header(payload)
    title = _extract_title(header)
    return TeiHeaderPayload(title=title, payload=header)
