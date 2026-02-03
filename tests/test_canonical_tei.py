"""Unit tests for TEI header parsing."""

from __future__ import annotations

import typing as typ

import pytest
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


def test_parse_tei_header_raises_type_error_when_header_missing() -> None:
    """TEI without a header should raise TypeError."""
    xml_without_header = """
    <TEI>
      <text>
        <body>
          <p>Content without header</p>
        </body>
      </text>
    </TEI>
    """

    with pytest.raises(TypeError, match="TEI header missing"):
        parse_tei_header(xml_without_header)


def test_parse_tei_header_raises_value_error_when_title_missing_or_blank() -> None:
    """TEI with a header but missing/empty title should raise ValueError."""
    xml_with_header_without_title = """
    <TEI>
      <teiHeader>
        <fileDesc>
          <titleStmt>
            <title></title>
          </titleStmt>
        </fileDesc>
      </teiHeader>
      <text>
        <body>
          <p>Content with header but no title</p>
        </body>
      </text>
    </TEI>
    """

    with pytest.raises(ValueError, match="TEI header title missing"):
        parse_tei_header(xml_with_header_without_title)
