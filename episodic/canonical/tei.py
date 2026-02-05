"""TEI parsing helpers built on tei-rapporteur."""

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
    payload = tei.to_dict(document)
    header = payload.get("teiHeader") or payload.get("header")
    if not isinstance(header, dict):
        msg = "TEI header missing from parsed payload."
        raise TypeError(msg)
    file_desc = header.get("fileDesc") or header.get("file_desc") or {}
    title = file_desc.get("title")
    if not isinstance(title, str) or not title.strip():
        msg = "TEI header title missing from parsed payload."
        raise ValueError(msg)

    return TeiHeaderPayload(title=title, payload=header)
