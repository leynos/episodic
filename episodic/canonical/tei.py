"""TEI parsing helpers built on tei-rapporteur."""

from __future__ import annotations

import dataclasses as dc
import typing as typ

import tei_rapporteur as _tei

TEI: typ.Any = _tei


@dc.dataclass(frozen=True)
class TeiHeaderPayload:
    """Parsed TEI header payload and derived metadata."""

    title: str
    payload: dict[str, typ.Any]


def parse_tei_header(xml: str) -> TeiHeaderPayload:
    """Parse a TEI XML payload and extract the header."""
    document = TEI.parse_xml(xml)
    document.validate()
    payload = TEI.to_dict(document)
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
