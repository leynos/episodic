"""LLM response parsing tests for ``ChapterMarkersGenerator``."""

import json

import pytest
from chapter_marker_generation_helpers import make_generator, valid_llm_response

from episodic.generation.chapter_markers import ChapterMarkersResponseFormatError


def test_result_from_response_parses_valid_json() -> None:
    """Parse a well-formed JSON response into a ChapterMarkersResult."""
    response = valid_llm_response(
        json.dumps({
            "chapters": [
                {
                    "title": " Introduction ",
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

    result = make_generator()._result_from_response(response)

    assert len(result.chapters) == 2
    assert result.chapters[0].title == "Introduction"
    assert result.chapters[0].start == "PT0S"
    assert result.chapters[0].tei_locator == "#seg-intro"
    assert result.chapters[1].duration == "PT10M"
    assert result.usage.total_tokens == 15


@pytest.mark.parametrize(
    ("response_text", "expected_match"),
    [
        ("not valid json {", "valid JSON"),
        ('"just a string"', "response"),
        ("[]", "response"),
        ("42", "response"),
        ("null", "response"),
        ("true", "response"),
        (json.dumps({"not_chapters": []}), "chapters"),
        (json.dumps({"chapters": {}}), "chapters"),
        (json.dumps({"chapters": ["not-an-object"]}), "chapter"),
        (json.dumps({"chapters": [{"start": "PT0S"}]}), "title"),
        (json.dumps({"chapters": [{"title": "Intro"}]}), "start"),
        (json.dumps({"chapters": [{"title": "Intro", "start": 0}]}), "start"),
        (
            json.dumps({
                "chapters": [{"title": "Intro", "start": "PT0S", "summary": 42}]
            }),
            "summary",
        ),
        (
            json.dumps({
                "chapters": [{"title": "Intro", "start": "PT0S", "tei_locator": 42}]
            }),
            "tei_locator",
        ),
    ],
)
def test_result_from_response_rejects_bad_input(
    response_text: str,
    expected_match: str,
) -> None:
    """Raise ChapterMarkersResponseFormatError.

    Any malformed or invalid LLM response is rejected.
    """
    with pytest.raises(ChapterMarkersResponseFormatError, match=expected_match):
        make_generator()._result_from_response(valid_llm_response(response_text))
