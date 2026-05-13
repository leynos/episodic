"""Show-notes DTO and JSON parsing tests."""

import json
import typing as typ
from unittest import mock

import pytest

from episodic.generation.show_notes import (
    ShowNotesEntry,
    ShowNotesGenerator,
    ShowNotesGeneratorConfig,
    ShowNotesResponseFormatError,
)
from tests import show_notes_support

if typ.TYPE_CHECKING:
    from episodic.llm import LLMPort


@pytest.fixture
def show_notes_generator() -> ShowNotesGenerator:
    """Create a generator for response-parsing tests."""
    config = ShowNotesGeneratorConfig(model="test-model")
    return ShowNotesGenerator(llm=typ.cast("LLMPort", mock.Mock()), config=config)


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


def test_result_from_response_parses_valid_json(
    show_notes_generator: ShowNotesGenerator,
) -> None:
    """Parse a well-formed JSON response into a ShowNotesResult."""
    json_text = json.dumps({
        "entries": [
            {"topic": "Topic 1", "summary": "Summary 1"},
            {"topic": "Topic 2", "summary": "Summary 2", "timestamp": "PT5M"},
        ]
    })
    response = show_notes_support.valid_llm_response(json_text)

    result = show_notes_generator._result_from_response(response)

    assert len(result.entries) == 2
    assert result.entries[0].topic == "Topic 1"
    assert result.entries[1].timestamp == "PT5M"


@pytest.mark.parametrize(
    ("json_payload", "expected_match"),
    [
        ({"entries": {}}, "entries"),
        ({"entries": ["not-an-object"]}, "entry"),
        ({"entries": [{"summary": "Summary only"}]}, "topic"),
        ({"entries": [{"topic": "Topic only"}]}, "summary"),
        ({"entries": [{"topic": "T", "summary": "S", "timestamp": 300}]}, "timestamp"),
        (
            {"entries": [{"topic": "T", "summary": "S", "tei_locator": 42}]},
            "tei_locator",
        ),
    ],
)
def test_result_from_response_rejects_malformed_entries(
    json_payload: dict[str, object],
    expected_match: str | None,
    show_notes_generator: ShowNotesGenerator,
) -> None:
    """Raise ShowNotesResponseFormatError for every malformed entry shape."""
    response = show_notes_support.valid_llm_response(json.dumps(json_payload))
    with pytest.raises(ShowNotesResponseFormatError, match=expected_match):
        show_notes_generator._result_from_response(response)


def test_result_from_response_raises_on_missing_entries_key(
    show_notes_generator: ShowNotesGenerator,
) -> None:
    """Raise ShowNotesResponseFormatError when the entries key is missing."""
    json_text = json.dumps({"summary": "No entries key"})
    response = show_notes_support.valid_llm_response(json_text)

    with pytest.raises(ShowNotesResponseFormatError, match="entries"):
        show_notes_generator._result_from_response(response)


def test_result_from_response_raises_on_invalid_json(
    show_notes_generator: ShowNotesGenerator,
) -> None:
    """Raise ShowNotesResponseFormatError when response text is not JSON."""
    response = show_notes_support.valid_llm_response("not valid json {")

    with pytest.raises(ShowNotesResponseFormatError):
        show_notes_generator._result_from_response(response)


def test_result_from_response_raises_on_empty_topic(
    show_notes_generator: ShowNotesGenerator,
) -> None:
    """Raise ShowNotesResponseFormatError when an entry has an empty topic."""
    json_text = json.dumps({"entries": [{"topic": "  ", "summary": "Valid summary"}]})
    response = show_notes_support.valid_llm_response(json_text)

    with pytest.raises(ShowNotesResponseFormatError):
        show_notes_generator._result_from_response(response)


@pytest.mark.parametrize("timestamp", ["5:30", "   "])
def test_result_from_response_rejects_non_iso8601_timestamp_strings(
    timestamp: str,
    show_notes_generator: ShowNotesGenerator,
) -> None:
    """Raise when `timestamp` is a string but not an ISO 8601 duration."""
    response = show_notes_support.valid_llm_response(
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
    with pytest.raises(ShowNotesResponseFormatError, match="ISO 8601"):
        show_notes_generator._result_from_response(response)


def test_show_notes_entry_normalizes_blank_locator_to_none() -> None:
    """Blank locator text should not survive into TEI `@corresp` values."""
    entry = ShowNotesEntry(
        topic="Introduction",
        summary="Opening remarks",
        tei_locator="   ",
    )

    assert entry.tei_locator is None
