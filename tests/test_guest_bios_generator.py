"""Guest biography prompt and generator tests."""

import json
import typing as typ

import pytest

from episodic.generation.guest_bios import (
    GuestBioEntry,
    GuestBiosGenerator,
    GuestBiosGeneratorConfig,
    GuestBioSource,
)
from tests._guest_bios_helpers import SCRIPT_TEI, _FakeLLMPort, _response

if typ.TYPE_CHECKING:
    from syrupy.assertion import SnapshotAssertion


def test_build_prompt_includes_guest_profile_sources(
    snapshot: SnapshotAssertion,
) -> None:
    """Include pinned profile content and identifiers in the LLM prompt."""
    source = GuestBioSource(
        display_name="Ada Lovelace",
        role="Mathematician",
        reference_document_id="doc-ada",
        reference_document_revision_id="rev-ada",
        source_content="Ada wrote notes on the Analytical Engine.",
    )

    prompt = GuestBiosGenerator.build_prompt(
        SCRIPT_TEI,
        (source,),
        template_structure={"segments": ["intro"]},
    )
    payload = json.loads(prompt)

    assert payload["script_tei_xml"] == SCRIPT_TEI, "Expected values to match"
    assert payload["template_structure"] == {"segments": ["intro"]}, (
        "Expected values to match"
    )
    assert payload["guest_profiles"] == snapshot, "actual output must match snapshot"


@pytest.mark.asyncio
async def test_generate_calls_llm_and_returns_guest_bios_result() -> None:
    """Call the LLM port and parse the response against expected revisions."""
    llm = _FakeLLMPort(
        response=_response({
            "guests": [
                {
                    "display_name": "Ada Lovelace",
                    "bio": "Ada Lovelace wrote about analytical engines.",
                    "reference_document_revision_id": "rev-ada",
                }
            ]
        }),
        requests=[],
    )
    generator = GuestBiosGenerator(
        llm=llm,
        config=GuestBiosGeneratorConfig(model="vidai-mock"),
    )
    source = GuestBioSource(
        display_name="Ada Lovelace",
        reference_document_id="doc-ada",
        reference_document_revision_id="rev-ada",
        source_content="Ada wrote notes on the Analytical Engine.",
    )

    result = await generator.generate(SCRIPT_TEI, (source,))

    assert len(llm.requests) == 1, "Expected values to match"
    assert llm.requests[0].model == "vidai-mock", "Expected values to match"
    assert "Ada wrote notes on the Analytical Engine." in llm.requests[0].prompt, (
        "Expected collection to contain the value"
    )
    assert result.entries == (
        GuestBioEntry(
            display_name="Ada Lovelace",
            bio="Ada Lovelace wrote about analytical engines.",
            reference_document_revision_id="rev-ada",
        ),
    ), "Expected values to match"
