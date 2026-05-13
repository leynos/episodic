"""Async and property tests for ``ChapterMarkersGenerator.generate``."""

import asyncio
import json

import hypothesis.strategies as st
import pytest
from chapter_marker_generation_helpers import (
    SEGMENT_STRUCTURE,
    BlockingLLMPort,
    FakeLLMPort,
    iso_duration,
    make_generator,
    minimal_tei,
    valid_llm_response,
)
from hypothesis import given, settings

from episodic.generation.chapter_markers import ChapterMarkersResponseFormatError


@pytest.mark.asyncio
async def test_generate_supports_concurrent_calls() -> None:
    """Concurrent generation calls remain independent and record every request."""
    llm = FakeLLMPort(
        valid_llm_response(
            json.dumps({"chapters": [{"title": "Intro", "start": "PT0S"}]})
        )
    )
    generator = make_generator(llm)

    results = await asyncio.gather(
        generator.generate(minimal_tei()),
        generator.generate(minimal_tei()),
    )

    assert [result.chapters[0].title for result in results] == ["Intro", "Intro"]
    assert len(llm.requests) == 2


@pytest.mark.asyncio
async def test_generate_propagates_timeout_cancellation() -> None:
    """Caller-managed timeouts cancel the pending LLM call cleanly."""
    llm = BlockingLLMPort()
    generator = make_generator(llm)

    with pytest.raises(TimeoutError):
        await asyncio.wait_for(generator.generate(minimal_tei()), timeout=0.01)

    assert llm.started.is_set()


@pytest.mark.asyncio
async def test_generate_calls_llm_and_returns_result() -> None:
    """The generate method calls the LLM and parses chapter markers."""
    fake_llm = FakeLLMPort(
        valid_llm_response(
            json.dumps({"chapters": [{"title": "Introduction", "start": "PT0S"}]})
        )
    )

    result = await make_generator(fake_llm).generate(
        minimal_tei(),
        segment_structure={"segments": [{"id": "seg-intro", "start": "PT0S"}]},
    )

    assert len(fake_llm.requests) == 1
    assert len(result.chapters) == 1
    assert result.chapters[0].title == "Introduction"
    assert fake_llm.requests[0].model == "test-model"


@pytest.mark.asyncio
async def test_generate_accepts_equivalent_duration_spellings() -> None:
    """Segment alignment compares elapsed time, not raw duration spelling."""
    fake_llm = FakeLLMPort(
        valid_llm_response(
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

    result = await make_generator(fake_llm).generate(
        minimal_tei(),
        segment_structure={
            "segments": [{"id": "seg-main", "title": "Main", "start": "PT330S"}]
        },
    )

    assert result.chapters[0].start == "PT5M30S"


@pytest.mark.asyncio
async def test_generate_rejects_conflicting_segment_locator_reuse() -> None:
    """Segment metadata cannot reuse a locator for different starts."""
    fake_llm = FakeLLMPort(
        valid_llm_response(
            json.dumps({"chapters": [{"title": "Introduction", "start": "PT0S"}]})
        )
    )

    with pytest.raises(
        ChapterMarkersResponseFormatError,
        match="Conflicting locator reuse",
    ):
        await make_generator(fake_llm).generate(
            minimal_tei(),
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
    fake_llm = FakeLLMPort(
        valid_llm_response(json.dumps({"chapters": chapters_payload}))
    )

    with pytest.raises(ChapterMarkersResponseFormatError, match=expected_match):
        await make_generator(fake_llm).generate(
            minimal_tei(),
            segment_structure=SEGMENT_STRUCTURE,
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
            {"id": f"seg-{i}", "start": iso_duration(s)}
            for i, s in enumerate(sorted_seconds)
        ]
    }
    chapters_payload = [
        {"title": f"Chapter {i}", "start": iso_duration(s)}
        for i, s in enumerate(sorted_seconds)
    ]
    fake_llm = FakeLLMPort(
        valid_llm_response(json.dumps({"chapters": chapters_payload}))
    )

    result = asyncio.run(
        make_generator(fake_llm).generate(
            minimal_tei(),
            segment_structure=segment_structure,
        )
    )

    assert len(result.chapters) == len(sorted_seconds)
    for chapter, seconds in zip(result.chapters, sorted_seconds, strict=True):
        assert chapter.start == iso_duration(seconds)


@given(start_secs=st.integers(min_value=0, max_value=3_600))
@settings(max_examples=30)
def test_repeated_locator_with_same_start_passes_validation(
    start_secs: int,
) -> None:
    """Segment metadata may reuse a locator key when it resolves to the same start."""
    duration = iso_duration(start_secs)
    # Both "seg-a" and "#seg-a" are generated from the id field by
    # _locator_keys_for_segment; they must both resolve to start_secs without
    # raising a conflicting-locator error.
    segment_structure: dict[str, object] = {
        "segments": [{"id": "seg-a", "start": duration}]
    }
    chapters_payload = [{"title": "Intro", "start": duration, "tei_locator": "#seg-a"}]
    fake_llm = FakeLLMPort(
        valid_llm_response(json.dumps({"chapters": chapters_payload}))
    )

    result = asyncio.run(
        make_generator(fake_llm).generate(
            minimal_tei(),
            segment_structure=segment_structure,
        )
    )

    assert len(result.chapters) == 1
    assert result.chapters[0].tei_locator == "#seg-a"
