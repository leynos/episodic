"""Tests for chapter-marker TEI enrichment.

These tests cover the XML-facing enrichment helper in
`episodic.generation.chapter_markers`. The DTO and generator/parser tests live
in focused neighbouring modules so TEI snapshot failures stay local to this
file.
"""

import asyncio
import collections.abc as cabc  # noqa: TC003 - Hypothesis evaluates annotations during collection
import re
import xml.sax.saxutils as xml_utils
from typing import TYPE_CHECKING  # noqa: ICN003 - requested direct type-checking guard

import hypothesis.strategies as st
import pytest
import tei_rapporteur as tei
from hypothesis import assume, given, settings

from episodic.generation.chapter_markers import (
    ChapterMarker,
    ChapterMarkersResult,
    enrich_tei_with_chapter_markers,
)
from episodic.llm import LLMUsage

if TYPE_CHECKING:
    from syrupy.assertion import SnapshotAssertion


@pytest.fixture(scope="module")
def minimal_tei() -> str:
    """Return a minimal TEI string."""
    return (
        '<TEI xmlns="http://www.tei-c.org/ns/1.0">'
        "<teiHeader><fileDesc><title>Test</title></fileDesc></teiHeader>"
        "<text><body>"
        '<p xml:id="seg-intro">Welcome and framing.</p>'
        '<p xml:id="seg-main">Main discussion.</p>'
        "</body></text>"
        "</TEI>"
    )


@pytest.fixture(scope="module")
def tei_with_existing_chapters() -> str:
    """Return a TEI string that already contains a chapters div."""
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


@pytest.fixture(scope="module")
def chapter_markers_result() -> cabc.Callable[..., ChapterMarkersResult]:
    """Return a factory for chapter-marker results."""

    def build_result(*chapters: ChapterMarker) -> ChapterMarkersResult:
        return ChapterMarkersResult(
            chapters=chapters,
            usage=LLMUsage(input_tokens=10, output_tokens=5, total_tokens=15),
        )

    return build_result


def test_enrich_tei_with_chapter_markers(
    minimal_tei: str,
    chapter_markers_result: cabc.Callable[..., ChapterMarkersResult],
    snapshot: SnapshotAssertion,
) -> None:
    """TEI body can be enriched with a div containing chapter markers."""
    enriched_xml = enrich_tei_with_chapter_markers(
        minimal_tei,
        chapter_markers_result(
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
    assert enriched_xml.count('type="chapters"') == 1, (
        "expected exactly one chapters div in enriched TEI"
    )
    assert '<item n="PT0S" corresp="#seg-intro">' in enriched_xml, (
        "expected intro chapter item with segment locator"
    )
    assert '<item n="PT5M30S" corresp="#seg-main">' in enriched_xml, (
        "expected main chapter item with segment locator"
    )
    assert "<label>Introduction</label>" in enriched_xml, (
        "expected introduction label in enriched TEI"
    )
    assert "The hosts begin the main topic." in enriched_xml, (
        "expected main chapter summary in enriched TEI"
    )
    assert enriched_xml == snapshot, "expected enriched TEI to match snapshot"


def test_enrich_tei_replaces_existing_chapters_div(
    tei_with_existing_chapters: str,
    chapter_markers_result: cabc.Callable[..., ChapterMarkersResult],
    snapshot: SnapshotAssertion,
) -> None:
    """Repeated enrichment should keep a single canonical chapters container."""
    enriched_xml = enrich_tei_with_chapter_markers(
        tei_with_existing_chapters,
        chapter_markers_result(
            ChapterMarker(title="New", start="PT0S", summary="Fresh summary")
        ),
    )

    assert enriched_xml.count('type="chapters"') == 1
    assert "Old summary" not in enriched_xml
    assert "<label>New</label>" in enriched_xml
    assert enriched_xml == snapshot


def test_enrich_tei_with_empty_result_returns_original(
    minimal_tei: str,
    chapter_markers_result: cabc.Callable[..., ChapterMarkersResult],
) -> None:
    """When the result has no chapters, return the original TEI unchanged."""
    original_xml = minimal_tei
    enriched_xml = enrich_tei_with_chapter_markers(
        original_xml,
        chapter_markers_result(),
    )

    assert enriched_xml == original_xml
    assert "<div" not in enriched_xml


def test_enrich_tei_with_empty_result_removes_existing_chapters(
    tei_with_existing_chapters: str,
    chapter_markers_result: cabc.Callable[..., ChapterMarkersResult],
    snapshot: SnapshotAssertion,
) -> None:
    """Empty chapter results remove stale chapter metadata from the TEI body."""
    enriched_xml = enrich_tei_with_chapter_markers(
        tei_with_existing_chapters,
        chapter_markers_result(),
    )

    document = tei.parse_xml(enriched_xml)
    document.validate()
    assert 'type="chapters"' not in enriched_xml
    assert "Old summary" not in enriched_xml
    assert enriched_xml == snapshot


def test_enrich_tei_escapes_xml_unsafe_characters(
    minimal_tei: str,
    chapter_markers_result: cabc.Callable[..., ChapterMarkersResult],
) -> None:
    """TEI enrichment properly escapes ampersands and angle brackets."""
    enriched_xml = enrich_tei_with_chapter_markers(
        minimal_tei,
        chapter_markers_result(
            ChapterMarker(
                title="Topic & More",
                start="PT0S",
                summary="Summary with <tags> & ampersands.",
            )
        ),
    )

    document = tei.parse_xml(enriched_xml)
    document.validate()
    assert "Summary with &lt;tags&gt; &amp; ampersands." in enriched_xml
    assert "Summary with <tags> & ampersands." not in enriched_xml


def test_enrich_tei_omits_content_when_summary_is_blank(
    minimal_tei: str,
    chapter_markers_result: cabc.Callable[..., ChapterMarkersResult],
) -> None:
    """Blank chapter summaries should not duplicate the title as item content."""
    enriched_xml = enrich_tei_with_chapter_markers(
        minimal_tei,
        chapter_markers_result(ChapterMarker(title="Introduction", start="PT0S")),
    )

    document = tei.parse_xml(enriched_xml)
    document.validate()
    assert "<label>Introduction</label>Introduction" not in enriched_xml
    assert '<item n="PT0S"><label>Introduction</label></item>' in enriched_xml


def test_enrich_tei_is_idempotent_for_same_result(
    minimal_tei: str,
    chapter_markers_result: cabc.Callable[..., ChapterMarkersResult],
) -> None:
    """Applying the same chapter result twice leaves one canonical chapter div."""
    result = chapter_markers_result(
        ChapterMarker(title="Introduction", start="PT0S", summary="Opening context.")
    )

    once = enrich_tei_with_chapter_markers(minimal_tei, result)
    twice = enrich_tei_with_chapter_markers(once, result)

    assert twice == once
    assert twice.count('type="chapters"') == 1


@pytest.mark.asyncio
async def test_enrich_tei_is_idempotent_across_concurrent_calls(
    minimal_tei: str,
    chapter_markers_result: cabc.Callable[..., ChapterMarkersResult],
) -> None:
    """Concurrent enrichment of the same inputs yields the same canonical XML."""
    result = chapter_markers_result(
        ChapterMarker(title="Introduction", start="PT0S", summary="Opening context.")
    )
    base_xml = enrich_tei_with_chapter_markers(minimal_tei, result)

    enriched_documents = await asyncio.gather(
        asyncio.to_thread(enrich_tei_with_chapter_markers, base_xml, result),
        asyncio.to_thread(enrich_tei_with_chapter_markers, base_xml, result),
    )

    assert enriched_documents == [base_xml, base_xml]


def test_enrich_tei_with_missing_body_raises_value_error(
    chapter_markers_result: cabc.Callable[..., ChapterMarkersResult],
) -> None:
    """Malformed TEI should raise ValueError rather than mutating blindly."""
    malformed_tei_xml = (
        '<TEI xmlns="http://www.tei-c.org/ns/1.0">'
        "<teiHeader><fileDesc><title>Test</title></fileDesc></teiHeader>"
        "<text><body><p>Hello</p></text>"
        "</TEI>"
    )

    with pytest.raises(ValueError, match=r"XML processing error"):
        enrich_tei_with_chapter_markers(
            malformed_tei_xml,
            chapter_markers_result(ChapterMarker(title="Intro", start="PT0S")),
        )


def test_enrich_tei_with_missing_payload_fields_raises_value_error(
    minimal_tei: str,
    chapter_markers_result: cabc.Callable[..., ChapterMarkersResult],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Structurally valid TEI missing payload fields should raise ValueError."""
    monkeypatch.setattr(
        tei,
        "to_dict",
        lambda _document: {"text": {"body": {}}},
    )

    with pytest.raises(ValueError, match=r"TEI payload field"):
        enrich_tei_with_chapter_markers(
            minimal_tei,
            chapter_markers_result(ChapterMarker(title="Intro", start="PT0S")),
        )


def _iso_duration(seconds: int) -> str:
    """Return an integer-only ISO 8601-style duration."""
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
    minimal_tei: str,
    chapter_markers_result: cabc.Callable[..., ChapterMarkersResult],
    starts: list[int],
) -> None:
    """Property test: strictly ordered starts survive validation and TEI output."""
    ordered_starts = sorted(starts)
    markers = tuple(
        ChapterMarker(title=f"Chapter {index}", start=_iso_duration(start))
        for index, start in enumerate(ordered_starts)
    )
    result = chapter_markers_result(*markers)

    enriched_xml = enrich_tei_with_chapter_markers(minimal_tei, result)

    document = tei.parse_xml(enriched_xml)
    document.validate()
    timing_sequence = re.findall(r'<item n="([^"]+)"', enriched_xml)
    assert timing_sequence == [marker.start for marker in markers], (
        "expected enriched chapter timings to preserve marker order"
    )


@given(summary=st.text(alphabet=" abcXYZ<&", max_size=50))
@settings(max_examples=50)
def test_arbitrary_summary_text_produces_valid_tei(
    minimal_tei: str,
    chapter_markers_result: cabc.Callable[..., ChapterMarkersResult],
    summary: str,
) -> None:
    """Property test: arbitrary summary text is escaped through TEI enrichment."""
    assume(summary.strip())
    result = chapter_markers_result(
        ChapterMarker(title="Chapter", start="PT0S", summary=summary)
    )
    enriched_xml = enrich_tei_with_chapter_markers(minimal_tei, result)

    document = tei.parse_xml(enriched_xml)
    document.validate()
    assert xml_utils.escape(summary.strip()) in enriched_xml
