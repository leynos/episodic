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


class TEIDocumentProtocol(typ.Protocol):
    """Typed TEI document surface needed for validation."""

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
    """Typed surface for tei_rapporteur interactions."""

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

    def to_dict(self, document: TEIDocumentProtocol) -> dict[str, typ.Any]:
        """Convert a TEI document into a dictionary payload.

        Parameters
        ----------
        document : TEIDocumentProtocol
            Parsed TEI document to serialise.

        Returns
        -------
        dict[str, typ.Any]
            Serialised TEI document dictionary.
        """
        ...


@dc.dataclass(frozen=True)
class TeiHeaderPayload:
    """Parsed TEI header payload and derived metadata."""

    title: str
    payload: dict[str, typ.Any]


def _parse_and_validate_tei(tei: TEIProtocol, xml: str) -> TEIDocumentProtocol:
    """Parse TEI XML and validate the document.

    Parameters
    ----------
    tei : TEIProtocol
        TEI parsing module interface.
    xml : str
        TEI XML payload to parse.

    Returns
    -------
    TEIDocumentProtocol
        Parsed and validated TEI document.

    Raises
    ------
    TypeError
        If the TEI header is missing from the parsed payload.
    ValueError
        If the TEI header title is missing from the parsed payload.
    ValueError
        If the TEI document is invalid and does not map to a known header issue.
    """
    try:
        document = tei.parse_xml(xml)
        document.validate()
    except ValueError as exc:
        message = str(exc)
        if "teiHeader" in message or "header" in message:
            msg = "TEI header missing from parsed payload."
            raise TypeError(msg) from exc
        if "title" in message:
            msg = "TEI header title missing from parsed payload."
            raise ValueError(msg) from exc
        raise
    return document


def _extract_header(payload: dict[str, typ.Any]) -> dict[str, typ.Any]:
    """Extract the TEI header from a parsed payload.

    Parameters
    ----------
    payload : dict[str, typ.Any]
        Parsed TEI document payload.

    Returns
    -------
    dict[str, typ.Any]
        Extracted TEI header payload.

    Raises
    ------
    TypeError
        If the TEI header is missing from the parsed payload.
    """
    header = payload.get("teiHeader") or payload.get("header")
    match header:
        case dict() as header_dict:
            return header_dict
        case _:
            msg = "TEI header missing from parsed payload."
            raise TypeError(msg)


def _extract_title(header: dict[str, typ.Any]) -> str:
    """Extract the TEI header title.

    Parameters
    ----------
    header : dict[str, typ.Any]
        TEI header payload.

    Returns
    -------
    str
        Extracted TEI header title.

    Raises
    ------
    ValueError
        If the TEI header title is missing from the parsed payload.
    """
    file_desc = header.get("fileDesc") or header.get("file_desc") or {}
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
    """
    tei = typ.cast("TEIProtocol", TEI)
    document = _parse_and_validate_tei(tei, xml)
    payload = tei.to_dict(document)
    header = _extract_header(payload)
    title = _extract_title(header)
    return TeiHeaderPayload(title=title, payload=header)
