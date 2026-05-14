"""Show-notes generator service tests."""

import json
import typing as typ

import pytest

from episodic.generation.show_notes import (
    ShowNotesGenerator,
    ShowNotesGeneratorConfig,
    ShowNotesResponseFormatError,
)
from tests import show_notes_support


@pytest.mark.asyncio
async def test_generate_calls_llm_and_returns_result() -> None:
    """The generate method calls the LLM and parses the response."""
    json_text = json.dumps({
        "entries": [{"topic": "Introduction", "summary": "Opening remarks"}]
    })
    fake_llm = show_notes_support.FakeLLMPort(
        show_notes_support.valid_llm_response(json_text)
    )

    config = ShowNotesGeneratorConfig(model="test-model")
    generator = ShowNotesGenerator(llm=fake_llm, config=config)

    script_xml = "<TEI><text><body><p>Test script.</p></body></text></TEI>"
    result = await generator.generate(script_xml)

    assert len(fake_llm.requests) == 1
    assert len(result.entries) == 1
    assert result.entries[0].topic == "Introduction"


@pytest.mark.asyncio
async def test_generate_sends_correct_llm_request_fields() -> None:
    """The outbound LLM request should honour the generator configuration."""
    fake_llm = show_notes_support.FakeLLMPort(
        show_notes_support.valid_llm_response(
            json.dumps({
                "entries": [{"topic": "Introduction", "summary": "Opening remarks"}]
            })
        )
    )
    config = ShowNotesGeneratorConfig(
        model="test-model",
        system_prompt="System prompt for tests.",
        token_budget=typ.cast("typ.Any", {"max_output_tokens": 128}),
    )
    generator = ShowNotesGenerator(llm=fake_llm, config=config)

    script_xml = "<TEI><text><body><p>Test script.</p></body></text></TEI>"
    await generator.generate(script_xml)

    assert len(fake_llm.requests) == 1
    request = fake_llm.requests[0]
    assert request.model == config.model
    assert request.system_prompt == config.system_prompt
    assert request.token_budget == config.token_budget


@pytest.mark.asyncio
async def test_generate_raises_on_unparseable_response() -> None:
    """The generate method raises ShowNotesResponseFormatError for bad JSON."""
    fake_llm = show_notes_support.FakeLLMPort(
        show_notes_support.valid_llm_response("invalid json")
    )

    config = ShowNotesGeneratorConfig(model="test-model")
    generator = ShowNotesGenerator(llm=fake_llm, config=config)

    script_xml = "<TEI><text><body><p>Test script.</p></body></text></TEI>"

    with pytest.raises(ShowNotesResponseFormatError, match="not valid JSON"):
        await generator.generate(script_xml)
