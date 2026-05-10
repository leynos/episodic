"""Tests for the chapter-marker content-enrichment boundary.

These tests cover the public DTOs, prompt builder, strict LLM response parser,
and TEI enrichment helper in `episodic.generation.chapter_markers`. Unit tests
exercise concrete parser and validation failures; Hypothesis properties cover
timing invariants over generated inputs; syrupy snapshots pin representative
TEI output while `tei_rapporteur` validation proves that the XML remains
parseable.

The module uses a small fake `LLMPort` so generator orchestration is tested
without an HTTP adapter. The live adapter path is covered separately by the
pytest-bdd Vidai Mock scenario in `tests/steps/test_chapter_markers_steps.py`.
"""

from __future__ import annotations

import json
import typing as typ

import hypothesis.strategies as st
import pytest
import tei_rapporteur as tei
from hypothesis import given, settings

from episodic.generation.chapter_markers import (
    ChapterMarker,
    ChapterMarkersGenerator,
    ChapterMarkersGeneratorConfig,
    ChapterMarkersResponseFormatError,
    ChapterMarkersResult,
    enrich_tei_with_chapter_markers,
)
from episodic.llm import LLMRequest, LLMResponse, LLMUsage

if typ.TYPE_CHECKING:
    from syrupy.assertion import SnapshotAssertion


class _FakeLLMPort:
    """Capture one chapter-marker request and return a canned response."""

    def __init__(self, response: LLMResponse) -> None:
        self.response = response
        self.requests: list[LLMRequest] = []

    async def generate(self, request: LLMRequest) -> LLMResponse:
        """Return the canned response and capture the request."""
        self.requests.append(request)
        return self.response


def _valid_llm_response(text: str) -> LLMResponse:
    return LLMResponse(
        text=text,
        model="test-model",
        provider_response_id="test-id",
        finish_reason="stop",
        usage=LLMUsage(input_tokens=10, output_tokens=5, total_tokens=15),
    )


def _minimal_tei() -> str:
    return (
        '<TEI xmlns="http://www.tei-c.org/ns/1.0">'
        "<teiHeader><fileDesc><title>Test</title></fileDesc></teiHeader>"
        "<text><body>"
        '<p xml:id="seg-intro">Welcome and framing.</p>'
        '<p xml:id="seg-main">Main discussion.</p>'
        "</body></text>"
        "</TEI>"
    )


def _tei_with_existing_chapters() -> str:
    return (
        '<TEI xmlns="http://www.tei-c.org/ns/1.0">'
        "<teiHeader><fileDesc><title>Test</title></fileDesc></teiHeader>"
        "<text><body>"
        "<p>Hello</p>"
        '<div type="chapters"><list><item n="PT0S">'
        "<label>Old</label>Old summary</item></list></div>"
        "</body></text>"
        "</TEI>"
    )


def _result(*chapters: ChapterMarker) -> ChapterMarkersResult:
    return ChapterMarkersResult(
        chapters=chapters,
        usage=LLMUsage(input_tokens=10, output_tokens=5, total_tokens=15),
    )


def test_chapter_marker_rejects_blank_title() -> None:
    """Reject blank title fields at construction time."""
    with pytest.raises(ValueError, match="title"):
        ChapterMarker(title="  ", start="PT0S")


def test_chapter_marker_rejects_invalid_start() -> None:
    """Reject start values that are not ISO 8601 durations."""
    with pytest.raises(ValueError, match="ISO 8601"):
        ChapterMarker(title="Introduction", start="00:00")


def test_chapter_marker_rejects_negative_start() -> None:
    """Reject negative ISO-like starts."""
    with pytest.raises(ValueError, match="non-negative"):
        ChapterMarker(title="Introduction", start="-PT1S")


def test_chapter_marker_normalizes_blank_optional_fields() -> None:
    """Blank optional text fields should not survive as TEI attributes."""
    marker = ChapterMarker(
        title="Introduction",
        start="PT0S",
        summary="",
        end="   ",
        duration="   ",
        tei_locator="   ",
    )

    assert marker.end is None
    assert marker.duration is None
    assert marker.tei_locator is None


@pytest.mark.parametrize("field_name", ["summary", "end", "duration", "tei_locator"])
def test_chapter_marker_rejects_non_string_optional_fields(field_name: str) -> None:
    """Optional text fields must fail with `ValueError`, not `AttributeError`."""
    kwargs: dict[str, object] = {
        "title": "Introduction",
        "start": "PT0S",
        field_name: 42,
    }

    with pytest.raises(TypeError, match=field_name):
        ChapterMarker(**typ.cast("typ.Any", kwargs))


@pytest.mark.parametrize("field_name", ["end", "duration"])
def test_chapter_marker_rejects_invalid_optional_duration(field_name: str) -> None:
    """Optional timing fields must also be ISO 8601 durations."""
    kwargs = {"title": "Introduction", "start": "PT0S", field_name: "1:00"}

    with pytest.raises(ValueError, match="ISO 8601"):
        ChapterMarker(**kwargs)


def test_chapter_markers_result_rejects_duplicate_or_descending_starts() -> None:
    """Chapter starts must be strictly increasing."""
    with pytest.raises(ValueError, match="strictly increasing"):
        _result(
            ChapterMarker(title="Intro", start="PT30S"),
            ChapterMarker(title="Main", start="PT30S"),
        )

    with pytest.raises(ValueError, match="strictly increasing"):
        _result(
            ChapterMarker(title="Main", start="PT30S"),
            ChapterMarker(title="Intro", start="PT0S"),
        )


def test_result_from_response_parses_valid_json() -> None:
    """Parse a well-formed JSON response into a ChapterMarkersResult."""
    response = _valid_llm_response(
        json.dumps({
            "chapters": [
                {
                    "title": "Introduction",
                    "start": "PT0S",
                    "summary": "Opening context.",
                    "tei_locator": "#seg-intro",
                },
                {
                    "title": "Main discussion",
                    "start": "PT5M30S",
                    "duration": "PT10M",
                },
            ]
        })
    )
    generator = ChapterMarkersGenerator(
        llm=typ.cast("typ.Any", None),
        config=ChapterMarkersGeneratorConfig(model="test-model"),
    )

    result = generator._result_from_response(response)

    assert len(result.chapters) == 2
    assert result.chapters[0].title == "Introduction"
    assert result.chapters[0].start == "PT0S"
    assert result.chapters[0].tei_locator == "#seg-intro"
    assert result.chapters[1].duration == "PT10M"
    assert result.usage.total_tokens == 15


@pytest.mark.parametrize(
    ("json_payload", "expected_match"),
    [
        ({"chapters": {}}, "chapters"),
        ({"chapters": ["not-an-object"]}, "chapter"),
        ({"chapters": [{"start": "PT0S"}]}, "title"),
        ({"chapters": [{"title": "Intro"}]}, "start"),
        ({"chapters": [{"title": "Intro", "start": 0}]}, "start"),
        (
            {"chapters": [{"title": "Intro", "start": "PT0S", "summary": 42}]},
            "summary",
        ),
        (
            {"chapters": [{"title": "Intro", "start": "PT0S", "tei_locator": 42}]},
            "tei_locator",
        ),
    ],
)
def test_result_from_response_rejects_malformed_chapters(
    json_payload: dict[str, object],
    expected_match: str,
) -> None:
    """Raise ChapterMarkersResponseFormatError for malformed chapter shapes."""
    response = _valid_llm_response(json.dumps(json_payload))
    generator = ChapterMarkersGenerator(
        llm=typ.cast("typ.Any", None),
        config=ChapterMarkersGeneratorConfig(model="test-model"),
    )

    with pytest.raises(ChapterMarkersResponseFormatError, match=expected_match):
        generator._result_from_response(response)


def test_result_from_response_raises_on_invalid_json() -> None:
    """Raise ChapterMarkersResponseFormatError when response text is not JSON."""
    response = _valid_llm_response("not valid json {")
    generator = ChapterMarkersGenerator(
        llm=typ.cast("typ.Any", None),
        config=ChapterMarkersGeneratorConfig(model="test-model"),
    )

    with pytest.raises(ChapterMarkersResponseFormatError, match="valid JSON"):
        generator._result_from_response(response)


def test_build_prompt_includes_tei_and_segment_structure() -> None:
    """The prompt embeds the TEI script and segment-transition metadata."""
    segment_structure: dict[str, object] = {
        "segments": [
            {"id": "seg-intro", "title": "Introduction", "start": "PT0S"},
            {"id": "seg-main", "title": "Main", "start": "PT5M30S"},
        ]
    }
    prompt = ChapterMarkersGenerator.build_prompt(
        _minimal_tei(),
        segment_structure=segment_structure,
    )
    payload = json.loads(prompt)

    assert payload == {
        "script_tei_xml": _minimal_tei(),
        "segment_structure": segment_structure,
    }


@pytest.mark.asyncio
async def test_generate_calls_llm_and_returns_result() -> None:
    """The generate method calls the LLM and parses chapter markers."""
    fake_llm = _FakeLLMPort(
        _valid_llm_response(
            json.dumps({"chapters": [{"title": "Introduction", "start": "PT0S"}]})
        )
    )
    generator = ChapterMarkersGenerator(
        llm=fake_llm,
        config=ChapterMarkersGeneratorConfig(model="test-model"),
    )

    result = await generator.generate(
        _minimal_tei(),
        segment_structure={"segments": [{"id": "seg-intro", "start": "PT0S"}]},
    )

    assert len(fake_llm.requests) == 1
    assert len(result.chapters) == 1
    assert result.chapters[0].title == "Introduction"
    assert fake_llm.requests[0].model == "test-model"


def test_enrich_tei_with_chapter_markers(snapshot: SnapshotAssertion) -> None:
    """TEI body can be enriched with a div containing chapter markers."""
    enriched_xml = enrich_tei_with_chapter_markers(
        _minimal_tei(),
        _result(
            ChapterMarker(
                title="Introduction",
                start="PT0S",
                summary="Opening context.",
                tei_locator="#seg-intro",
            ),
            ChapterMarker(
                title="Main discussion",
                start="PT5M30S",
                summary="The hosts begin the main topic.",
                duration="PT10M",
                tei_locator="#seg-main",
            ),
        ),
    )

    document = tei.parse_xml(enriched_xml)
    document.validate()
    assert enriched_xml.count('type="chapters"') == 1
    assert '<item n="PT0S" corresp="#seg-intro">' in enriched_xml
    assert '<item n="PT5M30S" corresp="#seg-main">' in enriched_xml
    assert "<label>Introduction</label>" in enriched_xml
    assert "The hosts begin the main topic." in enriched_xml
    assert enriched_xml == snapshot


def test_enrich_tei_replaces_existing_chapters_div() -> None:
    """Repeated enrichment should keep a single canonical chapters container."""
    enriched_xml = enrich_tei_with_chapter_markers(
        _tei_with_existing_chapters(),
        _result(ChapterMarker(title="New", start="PT0S", summary="Fresh summary")),
    )

    assert enriched_xml.count('type="chapters"') == 1
    assert "Old summary" not in enriched_xml
    assert "<label>New</label>" in enriched_xml


def test_enrich_tei_with_empty_result_returns_original() -> None:
    """When the result has no chapters, return the original TEI unchanged."""
    enriched_xml = enrich_tei_with_chapter_markers(_minimal_tei(), _result())

    assert "<div" not in enriched_xml


def test_enrich_tei_with_empty_result_removes_existing_chapters(
    snapshot: SnapshotAssertion,
) -> None:
    """Empty chapter results remove stale chapter metadata from the TEI body."""
    enriched_xml = enrich_tei_with_chapter_markers(
        _tei_with_existing_chapters(),
        _result(),
    )

    document = tei.parse_xml(enriched_xml)
    document.validate()
    assert 'type="chapters"' not in enriched_xml
    assert "Old summary" not in enriched_xml
    assert enriched_xml == snapshot


def test_enrich_tei_escapes_xml_unsafe_characters() -> None:
    """TEI enrichment properly escapes ampersands and angle brackets."""
    enriched_xml = enrich_tei_with_chapter_markers(
        _minimal_tei(),
        _result(
            ChapterMarker(
                title="Topic & More",
                start="PT0S",
                summary="Summary with <tags> & ampersands.",
            )
        ),
    )

    document = tei.parse_xml(enriched_xml)
    document.validate()
    assert "&amp;" in enriched_xml
    assert "&lt;" in enriched_xml or "<tags>" not in enriched_xml


def test_enrich_tei_is_idempotent_for_same_result() -> None:
    """Applying the same chapter result twice leaves one canonical chapter div."""
    result = _result(
        ChapterMarker(title="Introduction", start="PT0S", summary="Opening context.")
    )

    once = enrich_tei_with_chapter_markers(_minimal_tei(), result)
    twice = enrich_tei_with_chapter_markers(once, result)

    assert twice == once
    assert twice.count('type="chapters"') == 1


def test_enrich_tei_with_missing_body_raises_value_error() -> None:
    """Malformed TEI should raise ValueError rather than mutating blindly."""
    malformed_tei_xml = (
        '<TEI xmlns="http://www.tei-c.org/ns/1.0">'
        "<teiHeader><fileDesc><title>Test</title></fileDesc></teiHeader>"
        "<text><body><p>Hello</p></text>"
        "</TEI>"
    )

    with pytest.raises(ValueError, match=r"XML processing error|TEI payload field"):
        enrich_tei_with_chapter_markers(
            malformed_tei_xml,
            _result(ChapterMarker(title="Intro", start="PT0S")),
        )


def _iso_duration(seconds: int) -> str:
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    parts = ["PT"]
    if hours:
        parts.append(f"{hours}H")
    if minutes:
        parts.append(f"{minutes}M")
    if secs or seconds == 0:
        parts.append(f"{secs}S")
    return "".join(parts)


@given(st.lists(st.integers(min_value=0, max_value=86_400), min_size=1, unique=True))
@settings(max_examples=50)
def test_ordered_timings_survive_validation_and_tei_enrichment(
    starts: list[int],
) -> None:
    """Property test: strictly ordered starts survive validation and TEI output."""
    ordered_starts = sorted(starts)
    markers = tuple(
        ChapterMarker(title=f"Chapter {index}", start=_iso_duration(start))
        for index, start in enumerate(ordered_starts)
    )
    result = _result(*markers)

    enriched_xml = enrich_tei_with_chapter_markers(_minimal_tei(), result)

    document = tei.parse_xml(enriched_xml)
    document.validate()
    for marker in markers:
        assert f'n="{marker.start}"' in enriched_xml


@given(seconds=st.integers(min_value=0, max_value=86_400))
@settings(max_examples=50)
def test_duration_formatter_round_trips_through_chapter_marker(seconds: int) -> None:
    """Property test: generated duration strings remain valid public DTO values."""
    marker = ChapterMarker(title="Chapter", start=_iso_duration(seconds))

    assert marker.start == _iso_duration(seconds)


@given(title=st.text(alphabet=" \t\n\r", max_size=20))
@settings(max_examples=25)
def test_blank_generated_titles_are_rejected(title: str) -> None:
    """Property test: arbitrary blank titles never produce chapter markers."""
    with pytest.raises(ValueError, match="title"):
        ChapterMarker(title=title, start="PT0S")


@given(locator=st.text(alphabet=" \t\n\r", max_size=20))
@settings(max_examples=25)
def test_blank_locators_normalize_to_none(locator: str) -> None:
    """Property test: blank locator strings cannot leak into TEI `@corresp`."""
    marker = ChapterMarker(title="Chapter", start="PT0S", tei_locator=locator)

    assert marker.tei_locator is None


@given(summary=st.text(alphabet=" abcXYZ<&", max_size=50))
@settings(max_examples=50)
def test_arbitrary_summary_text_produces_valid_tei(summary: str) -> None:
    """Property test: arbitrary summary text is escaped through TEI enrichment."""
    result = _result(ChapterMarker(title="Chapter", start="PT0S", summary=summary))
    enriched_xml = enrich_tei_with_chapter_markers(_minimal_tei(), result)

    document = tei.parse_xml(enriched_xml)
    document.validate()


@given(
    duplicate_start=st.integers(min_value=0, max_value=86_400),
    later_start=st.integers(min_value=1, max_value=86_400),
)
@settings(max_examples=50)
def test_unordered_or_duplicate_timings_are_rejected(
    duplicate_start: int,
    later_start: int,
) -> None:
    """Property test: duplicate and descending start sequences are invalid."""
    start = _iso_duration(duplicate_start)
    with pytest.raises(ValueError, match="strictly increasing"):
        _result(
            ChapterMarker(title="First", start=start),
            ChapterMarker(title="Second", start=start),
        )

    later = _iso_duration(duplicate_start + later_start)
    with pytest.raises(ValueError, match="strictly increasing"):
        _result(
            ChapterMarker(title="Later", start=later),
            ChapterMarker(title="Earlier", start=start),
        )
