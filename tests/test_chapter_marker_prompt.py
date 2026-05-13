"""Prompt-building tests for ``ChapterMarkersGenerator``."""

import json

from chapter_marker_generation_helpers import minimal_tei

from episodic.generation.chapter_markers import ChapterMarkersGenerator


def test_build_prompt_includes_tei_and_segment_structure() -> None:
    """The prompt embeds the TEI script and segment-transition metadata."""
    segment_structure: dict[str, object] = {
        "segments": [
            {"id": "seg-intro", "title": "Introduction", "start": "PT0S"},
            {"id": "seg-main", "title": "Main", "start": "PT5M30S"},
        ]
    }
    prompt = ChapterMarkersGenerator.build_prompt(
        minimal_tei(),
        segment_structure=segment_structure,
    )
    payload = json.loads(prompt)

    assert payload == {
        "script_tei_xml": minimal_tei(),
        "segment_structure": segment_structure,
    }


def test_build_prompt_omits_segment_structure_when_not_provided() -> None:
    """The prompt omits segment metadata when callers do not provide it."""
    prompt_without_segment_structure = ChapterMarkersGenerator.build_prompt(
        minimal_tei(),
    )
    prompt_with_none_segment_structure = ChapterMarkersGenerator.build_prompt(
        minimal_tei(),
        segment_structure=None,
    )

    assert prompt_without_segment_structure == prompt_with_none_segment_structure
    assert json.loads(prompt_without_segment_structure) == {
        "script_tei_xml": minimal_tei()
    }
