"""Tests for chapter-marker prompt building and LLM response parsing."""

import asyncio
import json
import typing as typ

import hypothesis.strategies as st
import pytest
from hypothesis import given, settings

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


_SEGMENT_STRUCTURE: dict[str, object] = {
    "segments": [
        {"id": "seg-intro", "title": "Introduction", "start": "PT0S"},
        {"id": "seg-main", "title": "Main", "start": "PT5M30S"},
    ]
}


def _make_generator(fake_llm: object = None) -> ChapterMarkersGenerator:
    return ChapterMarkersGenerator(
        llm=typ.cast("typ.Any", fake_llm),
        config=ChapterMarkersGeneratorConfig(model="test-model"),
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

    result = _make_generator()._result_from_response(response)

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
        _make_generator()._result_from_response(_valid_llm_response(response_text))


@pytest.mark.asyncio
async def test_generate_supports_concurrent_calls() -> None:
    """Concurrent generation calls remain independent and record every request."""
    llm = _FakeLLMPort(
        _valid_llm_response(
            json.dumps({"chapters": [{"title": "Intro", "start": "PT0S"}]})
        )
    )
    generator = _make_generator(llm)

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
    generator = _make_generator(llm)

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

    result = await _make_generator(fake_llm).generate(
        _minimal_tei(),
        segment_structure={"segments": [{"id": "seg-intro", "start": "PT0S"}]},
    )

    assert len(fake_llm.requests) == 1
    assert len(result.chapters) == 1
    assert result.chapters[0].title == "Introduction"
    assert fake_llm.requests[0].model == "test-model"


@pytest.mark.asyncio
async def test_generate_accepts_equivalent_duration_spellings() -> None:
    """Segment alignment compares elapsed time, not raw duration spelling."""
    fake_llm = _FakeLLMPort(
        _valid_llm_response(
            json.dumps({
                "chapters": [
                    {
                        "title": "Main",
                        "start": "PT5M30S",
                        "tei_locator": "#seg-main",
                    }
                ]
            })
        )
    )

    result = await _make_generator(fake_llm).generate(
        _minimal_tei(),
        segment_structure={
            "segments": [{"id": "seg-main", "title": "Main", "start": "PT330S"}]
        },
    )

    assert result.chapters[0].start == "PT5M30S"


@pytest.mark.asyncio
async def test_generate_rejects_conflicting_segment_locator_reuse() -> None:
    """Segment metadata cannot reuse a locator for different starts."""
    fake_llm = _FakeLLMPort(
        _valid_llm_response(
            json.dumps({"chapters": [{"title": "Introduction", "start": "PT0S"}]})
        )
    )

    with pytest.raises(
        ChapterMarkersResponseFormatError,
        match="Conflicting locator reuse",
    ):
        await _make_generator(fake_llm).generate(
            _minimal_tei(),
            segment_structure={
                "segments": [
                    {"id": "seg-intro", "title": "Introduction", "start": "PT0S"},
                    {"id": "seg-intro", "title": "Repeat", "start": "PT5M30S"},
                ]
            },
        )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("chapters_payload", "expected_match"),
    [
        (
            [
                {"title": "Introduction", "start": "PT1S"},
                {"title": "Main", "start": "PT2M"},
            ],
            "segment starts",
        ),
        (
            [
                {
                    "title": "Introduction",
                    "start": "PT5M30S",
                    "tei_locator": "#seg-intro",
                }
            ],
            "#seg-intro",
        ),
    ],
)
async def test_generate_rejects_misaligned_chapters(
    chapters_payload: list[dict[str, object]],
    expected_match: str,
) -> None:
    """Reject misaligned chapters.

    Chapter starts or locators violating segment-transition constraints fail.
    """
    fake_llm = _FakeLLMPort(
        _valid_llm_response(json.dumps({"chapters": chapters_payload}))
    )

    with pytest.raises(ChapterMarkersResponseFormatError, match=expected_match):
        await _make_generator(fake_llm).generate(
            _minimal_tei(),
            segment_structure=_SEGMENT_STRUCTURE,
        )


@given(
    segment_seconds=st.lists(
        st.integers(min_value=0, max_value=3_600),
        min_size=1,
        max_size=5,
        unique=True,
    )
)
@settings(max_examples=30)
def test_aligned_chapters_pass_segment_validation(
    segment_seconds: list[int],
) -> None:
    """Accept chapters that exactly match all segment-transition starts."""
    sorted_seconds = sorted(segment_seconds)
    segment_structure: dict[str, object] = {
        "segments": [
            {"id": f"seg-{i}", "start": _iso_duration(s)}
            for i, s in enumerate(sorted_seconds)
        ]
    }
    chapters_payload = [
        {"title": f"Chapter {i}", "start": _iso_duration(s)}
        for i, s in enumerate(sorted_seconds)
    ]
    fake_llm = _FakeLLMPort(
        _valid_llm_response(json.dumps({"chapters": chapters_payload}))
    )

    result = asyncio.run(
        _make_generator(fake_llm).generate(
            _minimal_tei(),
            segment_structure=segment_structure,
        )
    )

    assert len(result.chapters) == len(sorted_seconds)
    for chapter, seconds in zip(result.chapters, sorted_seconds, strict=True):
        assert chapter.start == _iso_duration(seconds)


@given(start_secs=st.integers(min_value=0, max_value=3_600))
@settings(max_examples=30)
def test_repeated_locator_with_same_start_passes_validation(
    start_secs: int,
) -> None:
    """Segment metadata may reuse a locator key when it resolves to the same start."""
    duration = _iso_duration(start_secs)
    # Both "seg-a" and "#seg-a" are generated from the id field by
    # _locator_keys_for_segment; they must both resolve to start_secs without
    # raising a conflicting-locator error.
    segment_structure: dict[str, object] = {
        "segments": [{"id": "seg-a", "start": duration}]
    }
    chapters_payload = [{"title": "Intro", "start": duration, "tei_locator": "#seg-a"}]
    fake_llm = _FakeLLMPort(
        _valid_llm_response(json.dumps({"chapters": chapters_payload}))
    )

    result = asyncio.run(
        _make_generator(fake_llm).generate(
            _minimal_tei(),
            segment_structure=segment_structure,
        )
    )

    assert len(result.chapters) == 1
    assert result.chapters[0].tei_locator == "#seg-a"
