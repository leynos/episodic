"""Unit tests for show notes generation and TEI enrichment."""

import json
import typing as typ

import pytest
import tei_rapporteur as tei

from episodic.generation.show_notes import (
    ShowNotesEntry,
    ShowNotesGenerator,
    ShowNotesGeneratorConfig,
    ShowNotesResponseFormatError,
    ShowNotesResult,
    enrich_tei_with_show_notes,
)
from episodic.llm import (
    LLMRequest,
    LLMResponse,
    LLMUsage,
)


class _FakeLLMPort:
    """Capture one show-notes request and return a canned response."""

    def __init__(self, response: LLMResponse) -> None:
        self.response = response
        self.requests: list[LLMRequest] = []

    async def generate(self, request: LLMRequest) -> LLMResponse:
        """Return the canned response and capture the request."""
        self.requests.append(request)
        return self.response


# ── Stage B: TEI enrichment prototype ──


def test_prototype_tei_enrichment_with_show_notes() -> None:
    """Prototype test: TEI body can be enriched with a div containing show notes."""
    # Arrange: minimal TEI with one paragraph
    # Note: using the simplified tei_rapporteur structure without titleStmt
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

    # Act: enrich the TEI with show notes
    enriched_xml = enrich_tei_with_show_notes(minimal_tei_xml, result)

    # Assert: the enriched document parses and validates
    document = tei.parse_xml(enriched_xml)
    document.validate()

    # Assert: the enriched document contains the show notes div
    assert "<div" in enriched_xml
    assert 'type="notes"' in enriched_xml
    assert "<list>" in enriched_xml
    assert "<item" in enriched_xml
    assert 'n="PT0M30S"' in enriched_xml
    assert 'corresp="#p1"' in enriched_xml
    assert "<label>Introduction</label>" in enriched_xml
    assert "Opening remarks about the topic." in enriched_xml


# ── Stage C: DTO and JSON parsing tests ──


def test_show_notes_entry_rejects_empty_topic() -> None:
    """Reject blank topic fields at construction time."""
    with pytest.raises(ValueError, match="topic"):
        ShowNotesEntry(topic="  ", summary="Summary text")


def test_show_notes_entry_rejects_empty_summary() -> None:
    """Reject blank summary fields at construction time."""
    with pytest.raises(ValueError, match="summary"):
        ShowNotesEntry(topic="Topic", summary="  ")


def test_show_notes_entry_accepts_optional_timestamp() -> None:
    """Allow optional timestamp metadata."""
    entry = ShowNotesEntry(
        topic="Introduction", summary="Opening remarks", timestamp="PT1M30S"
    )
    assert entry.timestamp == "PT1M30S"


def test_show_notes_entry_rejects_non_iso8601_timestamp() -> None:
    """Reject timestamp metadata that is not an ISO 8601 duration."""
    with pytest.raises(ValueError, match="ISO 8601"):
        ShowNotesEntry(
            topic="Introduction",
            summary="Opening remarks",
            timestamp="5:30",
        )


def test_show_notes_entry_accepts_optional_locator() -> None:
    """Allow optional TEI locator metadata."""
    entry = ShowNotesEntry(
        topic="Introduction", summary="Opening remarks", tei_locator="#p1"
    )
    assert entry.tei_locator == "#p1"


def _valid_llm_response(text: str) -> LLMResponse:
    return LLMResponse(
        text=text,
        model="test-model",
        provider_response_id="test-id",
        finish_reason="stop",
        usage=LLMUsage(input_tokens=10, output_tokens=5, total_tokens=15),
    )


def test_result_from_response_parses_valid_json() -> None:
    """Parse a well-formed JSON response into a ShowNotesResult."""
    json_text = json.dumps({
        "entries": [
            {"topic": "Topic 1", "summary": "Summary 1"},
            {"topic": "Topic 2", "summary": "Summary 2", "timestamp": "PT5M"},
        ]
    })
    response = _valid_llm_response(json_text)

    config = ShowNotesGeneratorConfig(model="test-model")
    generator = ShowNotesGenerator(llm=typ.cast("typ.Any", None), config=config)
    result = generator._result_from_response(response)

    assert len(result.entries) == 2
    assert result.entries[0].topic == "Topic 1"
    assert result.entries[1].timestamp == "PT5M"


def test_result_from_response_raises_on_missing_entries_key() -> None:
    """Raise ShowNotesResponseFormatError when the entries key is missing."""
    json_text = json.dumps({"summary": "No entries key"})
    response = _valid_llm_response(json_text)

    config = ShowNotesGeneratorConfig(model="test-model")
    generator = ShowNotesGenerator(llm=typ.cast("typ.Any", None), config=config)

    with pytest.raises(ShowNotesResponseFormatError, match="entries"):
        generator._result_from_response(response)


def test_result_from_response_rejects_non_list_entries() -> None:
    """Raise when `entries` exists but is not a list."""
    response = _valid_llm_response(json.dumps({"entries": {}}))
    generator = ShowNotesGenerator(
        llm=typ.cast("typ.Any", None),
        config=ShowNotesGeneratorConfig(model="test-model"),
    )

    with pytest.raises(ShowNotesResponseFormatError, match="entries"):
        generator._result_from_response(response)


def test_result_from_response_rejects_non_object_entry_items() -> None:
    """Raise when `entries` contains non-object items."""
    response = _valid_llm_response(json.dumps({"entries": ["not-an-object"]}))
    generator = ShowNotesGenerator(
        llm=typ.cast("typ.Any", None),
        config=ShowNotesGeneratorConfig(model="test-model"),
    )

    with pytest.raises(ShowNotesResponseFormatError, match="entry"):
        generator._result_from_response(response)


def test_result_from_response_raises_on_invalid_json() -> None:
    """Raise ShowNotesResponseFormatError when response text is not JSON."""
    response = _valid_llm_response("not valid json {")

    config = ShowNotesGeneratorConfig(model="test-model")
    generator = ShowNotesGenerator(llm=typ.cast("typ.Any", None), config=config)

    with pytest.raises(ShowNotesResponseFormatError):
        generator._result_from_response(response)


def test_result_from_response_raises_on_empty_topic() -> None:
    """Raise ShowNotesResponseFormatError when an entry has an empty topic."""
    json_text = json.dumps({"entries": [{"topic": "  ", "summary": "Valid summary"}]})
    response = _valid_llm_response(json_text)

    config = ShowNotesGeneratorConfig(model="test-model")
    generator = ShowNotesGenerator(llm=typ.cast("typ.Any", None), config=config)

    with pytest.raises(ShowNotesResponseFormatError):
        generator._result_from_response(response)


@pytest.mark.parametrize(
    ("entry_payload", "field_name"),
    [
        ({"summary": "Summary only"}, "topic"),
        ({"topic": "Topic only"}, "summary"),
    ],
)
def test_result_from_response_requires_topic_and_summary(
    entry_payload: dict[str, str],
    field_name: str,
) -> None:
    """Raise when required `topic` or `summary` fields are missing."""
    response = _valid_llm_response(json.dumps({"entries": [entry_payload]}))
    generator = ShowNotesGenerator(
        llm=typ.cast("typ.Any", None),
        config=ShowNotesGeneratorConfig(model="test-model"),
    )

    with pytest.raises(ShowNotesResponseFormatError, match=field_name):
        generator._result_from_response(response)


@pytest.mark.parametrize(
    "entry_payload",
    [
        ({"topic": "Topic 1", "summary": "Summary 1", "timestamp": 300},),
        ({"topic": "Topic 2", "summary": "Summary 2", "tei_locator": 42},),
    ],
)
def test_result_from_response_rejects_non_string_optional_fields(
    entry_payload: dict[str, object],
) -> None:
    """Raise when optional fields are present but not strings."""
    response = _valid_llm_response(json.dumps({"entries": [entry_payload]}))
    generator = ShowNotesGenerator(
        llm=typ.cast("typ.Any", None),
        config=ShowNotesGeneratorConfig(model="test-model"),
    )

    with pytest.raises(ShowNotesResponseFormatError):
        generator._result_from_response(response)


@pytest.mark.parametrize("timestamp", ["5:30", "   "])
def test_result_from_response_rejects_non_iso8601_timestamp_strings(
    timestamp: str,
) -> None:
    """Raise when `timestamp` is a string but not an ISO 8601 duration."""
    response = _valid_llm_response(
        json.dumps({
            "entries": [
                {
                    "topic": "Topic 1",
                    "summary": "Summary 1",
                    "timestamp": timestamp,
                }
            ]
        })
    )
    generator = ShowNotesGenerator(
        llm=typ.cast("typ.Any", None),
        config=ShowNotesGeneratorConfig(model="test-model"),
    )

    with pytest.raises(ShowNotesResponseFormatError, match="ISO 8601"):
        generator._result_from_response(response)


# ── Stage D: Generator service tests ──


def test_build_prompt_includes_tei_xml() -> None:
    """The build_prompt static method includes the TEI XML in the prompt."""
    script_xml = "<TEI><text><body><p>Test script.</p></body></text></TEI>"
    prompt = ShowNotesGenerator.build_prompt(script_xml)

    assert "Test script." in prompt


@pytest.mark.asyncio
async def test_generate_calls_llm_and_returns_result() -> None:
    """The generate method calls the LLM and parses the response."""
    json_text = json.dumps({
        "entries": [{"topic": "Introduction", "summary": "Opening remarks"}]
    })
    fake_llm = _FakeLLMPort(_valid_llm_response(json_text))

    config = ShowNotesGeneratorConfig(model="test-model")
    generator = ShowNotesGenerator(llm=fake_llm, config=config)

    script_xml = "<TEI><text><body><p>Test script.</p></body></text></TEI>"
    result = await generator.generate(script_xml)

    assert len(fake_llm.requests) == 1
    assert len(result.entries) == 1
    assert result.entries[0].topic == "Introduction"


@pytest.mark.asyncio
async def test_generate_raises_on_unparseable_response() -> None:
    """The generate method raises ShowNotesResponseFormatError for bad JSON."""
    fake_llm = _FakeLLMPort(_valid_llm_response("invalid json"))

    config = ShowNotesGeneratorConfig(model="test-model")
    generator = ShowNotesGenerator(llm=fake_llm, config=config)

    script_xml = "<TEI><text><body><p>Test script.</p></body></text></TEI>"

    with pytest.raises(ShowNotesResponseFormatError):
        await generator.generate(script_xml)


# ── Stage E: TEI enrichment tests ──


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

    # The enriched XML should be functionally equivalent to the original
    # (whitespace differences are acceptable)
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

    # Assert: the XML parses and validates (confirms proper escaping)
    document = tei.parse_xml(enriched_xml)
    document.validate()

    # Assert: the escaped characters appear in the serialized form
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
