"""Unit tests for TEI header parsing."""

from __future__ import annotations

import typing as typ

import tei_rapporteur as _tei

from episodic.canonical.tei import parse_tei_header

TEI: typ.Any = _tei


def test_parse_tei_header_extracts_title() -> None:
    """Parsed headers surface the document title."""
    document = TEI.Document("Bridgewater")
    xml = TEI.emit_xml(document)

    header = parse_tei_header(xml)

    assert header.title == "Bridgewater"
    assert header.payload["file_desc"]["title"] == "Bridgewater"
