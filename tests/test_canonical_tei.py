"""Unit tests for TEI header parsing."""

from __future__ import annotations

import pytest
import tei_rapporteur as _tei

from episodic.canonical.tei import parse_tei_header


def test_parse_tei_header_extracts_title() -> None:
    """Parsed headers surface the document title."""
    document = _tei.Document("Bridgewater")  # type: ignore[unresolved-attribute]
    xml = _tei.emit_xml(document)  # type: ignore[unresolved-attribute]

    header = parse_tei_header(xml)

    assert header.title == "Bridgewater", (
        f"Expected header.title to be 'Bridgewater', got {header.title!r}."
    )
    assert header.payload["file_desc"]["title"] == "Bridgewater", (
        "Expected header.payload['file_desc']['title'] to be 'Bridgewater', "
        f"got {header.payload['file_desc']['title']!r}."
    )


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
