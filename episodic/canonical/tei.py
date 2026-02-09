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

import dataclasses as dc
import typing as typ

import tei_rapporteur as _tei

TEI = _tei  # pyright: ignore[reportUnknownMemberType]  # TODO(@codex): add type stubs for tei_rapporteur upstream (https://github.com/leynos/tei-rapporteur/issues/new)


type TEIPayload = dict[str, object]

_MISSING_HEADER_MESSAGE = "XML processing error: missing field `teiHeader`"
_MISSING_TITLE_MESSAGE = "XML processing error: missing field `title`"


class TEIDocumentProtocol(typ.Protocol):
    """Protocol for TEI document validation.

    Methods
    -------
    validate()
        Validate the parsed TEI document.
    """

    def validate(self) -> None:
        """Validate the parsed TEI document.

        Returns
        -------
        None

        Raises
        ------
        ValueError
            If the TEI document is invalid.
        """
        ...


class TEIProtocol(typ.Protocol):
    """Protocol for tei-rapporteur parser interactions.

    Methods
    -------
    parse_xml(xml)
        Parse a TEI XML payload into a document handle.
    to_dict(document)
        Serialize a TEI document into a dictionary payload.
    """

    def parse_xml(self, xml: str) -> TEIDocumentProtocol:
        """Parse TEI XML into a TEI document.

        Parameters
        ----------
        xml : str
            TEI XML payload to parse.

        Returns
        -------
        TEIDocumentProtocol
            Parsed TEI document handle.
        """
        ...

    def to_dict(self, document: TEIDocumentProtocol) -> TEIPayload:
        """Convert a TEI document into a dictionary payload.

        Parameters
        ----------
        document : TEIDocumentProtocol
            Parsed TEI document to serialize.

        Returns
        -------
        TEIPayload
            Serialized TEI document dictionary.
        """
        ...


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


def _parse_and_validate_tei(tei: TEIProtocol, xml: str) -> TEIDocumentProtocol:
    """Parse TEI XML and validate the document."""
    try:
        document = tei.parse_xml(xml)
        document.validate()
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
    tei = typ.cast("TEIProtocol", TEI)
    document = _parse_and_validate_tei(tei, xml)
    payload = tei.to_dict(document)
    header = _extract_header(payload)
    title = _extract_title(header)
    return TeiHeaderPayload(title=title, payload=header)
