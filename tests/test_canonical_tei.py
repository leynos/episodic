"""Unit tests for TEI header parsing."""

from __future__ import annotations

import typing as typ

import pytest
import tei_rapporteur as _tei

from episodic.canonical import tei as tei_module
from episodic.canonical.tei import parse_tei_header


def test_parse_tei_header_extracts_title() -> None:
    """Parsed headers surface the document title."""
    document = _tei.Document("Bridgewater")
    xml = _tei.emit_xml(document)

    header = parse_tei_header(xml)

    assert header.title == "Bridgewater", (
        f"Expected header.title to be 'Bridgewater', got {header.title!r}."
    )
    file_desc = typ.cast("tei_module.TEIPayload", header.payload["file_desc"])
    assert file_desc["title"] == "Bridgewater", (
        "Expected header.payload['file_desc']['title'] to be 'Bridgewater', "
        f"got {file_desc['title']!r}."
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


@pytest.mark.parametrize(
    "message",
    [
        "XML processing error: header invalid",
        "XML processing error: title malformed",
    ],
)
def test_parse_tei_header_preserves_unmapped_validation_errors(
    monkeypatch: pytest.MonkeyPatch,
    message: str,
) -> None:
    """Unmapped validation errors should surface unchanged."""

    class _DummyDocument:
        def __init__(self, exc: Exception) -> None:
            self._exc = exc

        def validate(self) -> None:
            raise self._exc

    dummy_document = _DummyDocument(ValueError(message))

    def _parse_xml(_xml: str) -> _DummyDocument:
        return dummy_document

    def _to_dict(_document: _DummyDocument) -> dict[str, object]:
        return {}

    monkeypatch.setattr(tei_module._tei, "parse_xml", _parse_xml)
    monkeypatch.setattr(tei_module._tei, "to_dict", _to_dict)
    with pytest.raises(ValueError, match=message):
        parse_tei_header("<TEI></TEI>")
