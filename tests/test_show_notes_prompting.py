"""Show-notes prompt construction tests."""

import typing as typ

from episodic.generation.show_notes import ShowNotesGenerator

if typ.TYPE_CHECKING:
    from syrupy.assertion import SnapshotAssertion


def test_build_prompt_includes_tei_xml() -> None:
    """The build_prompt static method includes the TEI XML in the prompt."""
    script_xml = "<TEI><text><body><p>Test script.</p></body></text></TEI>"
    prompt = ShowNotesGenerator.build_prompt(script_xml)

    assert "Test script." in prompt, "Expected collection to contain the value"


def test_build_prompt_includes_template_structure(snapshot: SnapshotAssertion) -> None:
    """The prompt should embed the optional template structure mapping."""
    script_xml = "<TEI><text><body><p>Test script.</p></body></text></TEI>"
    prompt = ShowNotesGenerator.build_prompt(
        script_xml,
        template_structure={"sections": ["intro", "main"]},
    )

    assert prompt == snapshot, "actual output must match snapshot"
