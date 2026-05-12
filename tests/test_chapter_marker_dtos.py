"""Unit and property tests for chapter-marker DTO validation."""

import typing as typ

import hypothesis.strategies as st
import pytest
from hypothesis import given, settings

from episodic.generation.chapter_markers import ChapterMarker, ChapterMarkersResult
from episodic.llm import LLMUsage


def _result(*chapters: ChapterMarker) -> ChapterMarkersResult:
    return ChapterMarkersResult(
        chapters=chapters,
        usage=LLMUsage(input_tokens=10, output_tokens=5, total_tokens=15),
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


def test_chapter_marker_rejects_blank_title() -> None:
    """Reject blank title fields at construction time."""
    with pytest.raises(ValueError, match="title"):
        ChapterMarker(title="  ", start="PT0S")


def test_chapter_marker_rejects_invalid_start() -> None:
    """Reject start values outside the supported duration subset."""
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
    """Optional text fields must fail with `TypeError`, not `AttributeError`."""
    kwargs: dict[str, object] = {
        "title": "Introduction",
        "start": "PT0S",
        field_name: 42,
    }

    with pytest.raises(TypeError, match=field_name):
        ChapterMarker(**typ.cast("typ.Any", kwargs))


@pytest.mark.parametrize("field_name", ["end", "duration"])
def test_chapter_marker_rejects_invalid_optional_duration(field_name: str) -> None:
    """Optional timing fields must also use the supported duration subset."""
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
