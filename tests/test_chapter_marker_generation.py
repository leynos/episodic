"""Tests for chapter-marker prompt building and LLM response parsing."""

from __future__ import annotations

import asyncio
import json
import typing as typ

import pytest

from episodic.generation.chapter_markers import (
    ChapterMarkersGenerator,
    ChapterMarkersGeneratorConfig,
    ChapterMarkersResponseFormatError,
)
from episodic.llm import LLMRequest, LLMResponse, LLMUsage


class _FakeLLMPort:
    """Capture one chapter-marker request and return a canned response."""

    def __init__(self, response: LLMResponse) -> None:
        self.response = response
        self.requests: list[LLMRequest] = []

    async def generate(self, request: LLMRequest) -> LLMResponse:
        """Return the canned response and capture the request."""
        self.requests.append(request)
        return self.response


class _BlockingLLMPort:
    """LLM fake that blocks until cancelled by the caller."""

    def __init__(self) -> None:
        self.started = asyncio.Event()

    async def generate(self, request: LLMRequest) -> LLMResponse:
        """Block indefinitely so timeout and cancellation behaviour is visible."""
        _ = request
        self.started.set()
        await asyncio.Event().wait()
        raise AssertionError("unreachable")


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


def test_result_from_response_parses_valid_json() -> None:
    """Parse a well-formed JSON response into a ChapterMarkersResult."""
    response = _valid_llm_response(
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


@pytest.mark.parametrize("payload", ['"just a string"', "[]", "42", "null", "true"])
def test_result_from_response_rejects_non_object_top_level_json(
    payload: str,
) -> None:
    """Non-object top-level JSON payloads must be rejected."""
    response = _valid_llm_response(payload)
    generator = ChapterMarkersGenerator(
        llm=typ.cast("typ.Any", None),
        config=ChapterMarkersGeneratorConfig(model="test-model"),
    )

    with pytest.raises(ChapterMarkersResponseFormatError, match="response"):
        generator._result_from_response(response)


def test_result_from_response_requires_chapters_key() -> None:
    """Objects without a `chapters` key must be rejected."""
    response = _valid_llm_response(json.dumps({"not_chapters": []}))
    generator = ChapterMarkersGenerator(
        llm=typ.cast("typ.Any", None),
        config=ChapterMarkersGeneratorConfig(model="test-model"),
    )

    with pytest.raises(ChapterMarkersResponseFormatError, match="chapters"):
        generator._result_from_response(response)


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


@pytest.mark.asyncio
async def test_generate_supports_concurrent_calls() -> None:
    """Concurrent generation calls remain independent and record every request."""
    llm = _FakeLLMPort(
        _valid_llm_response(
            json.dumps({"chapters": [{"title": "Intro", "start": "PT0S"}]})
        )
    )
    generator = ChapterMarkersGenerator(
        llm=llm,
        config=ChapterMarkersGeneratorConfig(model="test-model"),
    )

    results = await asyncio.gather(
        generator.generate(_minimal_tei()),
        generator.generate(_minimal_tei()),
    )

    assert [result.chapters[0].title for result in results] == ["Intro", "Intro"]
    assert len(llm.requests) == 2


@pytest.mark.asyncio
async def test_generate_propagates_timeout_cancellation() -> None:
    """Caller-managed timeouts cancel the pending LLM call cleanly."""
    llm = _BlockingLLMPort()
    generator = ChapterMarkersGenerator(
        llm=llm,
        config=ChapterMarkersGeneratorConfig(model="test-model"),
    )

    with pytest.raises(TimeoutError):
        await asyncio.wait_for(generator.generate(_minimal_tei()), timeout=0.01)

    assert llm.started.is_set()


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


def test_build_prompt_omits_segment_structure_when_not_provided() -> None:
    """The prompt omits segment metadata when callers do not provide it."""
    prompt_without_segment_structure = ChapterMarkersGenerator.build_prompt(
        _minimal_tei(),
    )
    prompt_with_none_segment_structure = ChapterMarkersGenerator.build_prompt(
        _minimal_tei(),
        segment_structure=None,
    )

    assert prompt_without_segment_structure == prompt_with_none_segment_structure
    assert json.loads(prompt_without_segment_structure) == {
        "script_tei_xml": _minimal_tei()
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


@pytest.mark.asyncio
async def test_generate_rejects_chapters_not_aligned_to_segment_starts() -> None:
    """Explicit segment starts constrain generated chapter starts."""
    fake_llm = _FakeLLMPort(
        _valid_llm_response(
            json.dumps({
                "chapters": [
                    {"title": "Introduction", "start": "PT1S"},
                    {"title": "Main", "start": "PT2M"},
                ]
            })
        )
    )
    generator = ChapterMarkersGenerator(
        llm=fake_llm,
        config=ChapterMarkersGeneratorConfig(model="test-model"),
    )

    with pytest.raises(ChapterMarkersResponseFormatError, match="segment starts"):
        await generator.generate(
            _minimal_tei(),
            segment_structure={
                "segments": [
                    {"id": "seg-intro", "title": "Introduction", "start": "PT0S"},
                    {"id": "seg-main", "title": "Main", "start": "PT5M30S"},
                ]
            },
        )


@pytest.mark.asyncio
async def test_generate_rejects_locator_with_mismatched_segment_start() -> None:
    """Chapter locators must resolve to the same supplied segment transition."""
    fake_llm = _FakeLLMPort(
        _valid_llm_response(
            json.dumps({
                "chapters": [
                    {
                        "title": "Introduction",
                        "start": "PT5M30S",
                        "tei_locator": "#seg-intro",
                    }
                ]
            })
        )
    )
    generator = ChapterMarkersGenerator(
        llm=fake_llm,
        config=ChapterMarkersGeneratorConfig(model="test-model"),
    )

    with pytest.raises(ChapterMarkersResponseFormatError, match="#seg-intro"):
        await generator.generate(
            _minimal_tei(),
            segment_structure={
                "segments": [
                    {"id": "seg-intro", "title": "Introduction", "start": "PT0S"},
                    {"id": "seg-main", "title": "Main", "start": "PT5M30S"},
                ]
            },
        )
