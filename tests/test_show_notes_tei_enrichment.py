"""Show-notes TEI enrichment tests."""

import pytest
import tei_rapporteur as tei

from episodic.generation.show_notes import (
    ShowNotesEntry,
    ShowNotesResult,
    enrich_tei_with_show_notes,
)
from episodic.llm import LLMUsage


def test_prototype_tei_enrichment_with_show_notes() -> None:
    """Prototype test: TEI body can be enriched with a div containing show notes."""
    minimal_tei_xml = (
        '<TEI xmlns="http://www.tei-c.org/ns/1.0">'
        "<teiHeader><fileDesc><title>Test</title></fileDesc></teiHeader>"
        '<text><body><p xml:id="p1">Hello world.</p></body></text>'
        "</TEI>"
    )

    result = ShowNotesResult(
        entries=(
            ShowNotesEntry(
                topic="Introduction",
                summary="Opening remarks about the topic.",
                timestamp="PT0M30S",
                tei_locator="#p1",
            ),
        ),
        usage=LLMUsage(input_tokens=10, output_tokens=5, total_tokens=15),
        model="test-model",
        provider_response_id="test-id",
        finish_reason="stop",
    )

    enriched_xml = enrich_tei_with_show_notes(minimal_tei_xml, result)

    document = tei.parse_xml(enriched_xml)
    document.validate()

    assert "<div" in enriched_xml
    assert 'type="notes"' in enriched_xml
    assert "<list>" in enriched_xml
    assert "<item" in enriched_xml
    assert 'n="PT0M30S"' in enriched_xml
    assert 'corresp="#p1"' in enriched_xml
    assert "<label>Introduction</label>" in enriched_xml
    assert "Opening remarks about the topic." in enriched_xml


def test_enrich_tei_with_empty_result_returns_original() -> None:
    """When the result has no entries, return the original TEI unchanged."""
    minimal_tei_xml = (
        '<TEI xmlns="http://www.tei-c.org/ns/1.0">'
        "<teiHeader><fileDesc><title>Test</title></fileDesc></teiHeader>"
        "<text><body><p>Hello</p></body></text>"
        "</TEI>"
    )

    empty_result = ShowNotesResult(
        entries=(),
        usage=LLMUsage(input_tokens=10, output_tokens=5, total_tokens=15),
    )

    enriched_xml = enrich_tei_with_show_notes(minimal_tei_xml, empty_result)

    assert "<div" not in enriched_xml


def test_enrich_tei_with_missing_body_raises_value_error() -> None:
    """Malformed TEI should raise ValueError rather than mutating blindly."""
    malformed_tei_xml = (
        '<TEI xmlns="http://www.tei-c.org/ns/1.0">'
        "<teiHeader><fileDesc><title>Test</title></fileDesc></teiHeader>"
        "<text><body><p>Hello</p></text>"
        "</TEI>"
    )

    result = ShowNotesResult(
        entries=(ShowNotesEntry(topic="Intro", summary="Opening remarks"),),
        usage=LLMUsage(input_tokens=10, output_tokens=5, total_tokens=15),
    )

    with pytest.raises(ValueError, match=r"XML processing error|TEI payload field"):
        enrich_tei_with_show_notes(malformed_tei_xml, result)


def test_enrich_tei_escapes_xml_unsafe_characters() -> None:
    """TEI enrichment properly escapes ampersands and angle brackets."""
    minimal_tei_xml = (
        '<TEI xmlns="http://www.tei-c.org/ns/1.0">'
        "<teiHeader><fileDesc><title>Test</title></fileDesc></teiHeader>"
        "<text><body><p>Hello</p></body></text>"
        "</TEI>"
    )

    result = ShowNotesResult(
        entries=(
            ShowNotesEntry(
                topic="Topic & More",
                summary="Summary with <tags> & ampersands.",
            ),
        ),
        usage=LLMUsage(input_tokens=10, output_tokens=5, total_tokens=15),
    )

    enriched_xml = enrich_tei_with_show_notes(minimal_tei_xml, result)

    document = tei.parse_xml(enriched_xml)
    document.validate()

    assert "&amp;" in enriched_xml
    assert "&lt;" in enriched_xml or "<tags>" not in enriched_xml


def test_enrich_tei_replaces_existing_notes_div() -> None:
    """Replacing show notes should keep a single canonical notes container."""
    tei_with_existing_notes = (
        '<TEI xmlns="http://www.tei-c.org/ns/1.0">'
        "<teiHeader><fileDesc><title>Test</title></fileDesc></teiHeader>"
        "<text><body>"
        "<p>Hello</p>"
        '<div type="notes"><list><item><label>Old topic</label>'
        "Old summary</item></list></div>"
        "</body></text>"
        "</TEI>"
    )
    result = ShowNotesResult(
        entries=(
            ShowNotesEntry(
                topic="New topic",
                summary="Fresh summary",
                timestamp="PT2M",
                tei_locator="#p1",
            ),
        ),
        usage=LLMUsage(input_tokens=10, output_tokens=5, total_tokens=15),
    )

    enriched_xml = enrich_tei_with_show_notes(tei_with_existing_notes, result)

    assert enriched_xml.count('type="notes"') == 1
    assert "Old topic" not in enriched_xml
    assert "Old summary" not in enriched_xml
    assert "<label>New topic</label>" in enriched_xml
    assert "Fresh summary" in enriched_xml
